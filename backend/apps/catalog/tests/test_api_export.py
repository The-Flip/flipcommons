"""Tests for the model-driven bulk-export API (``GET /api/export/<entity>/``)."""

from __future__ import annotations

from typing import Any

from constance.test import override_config

from apps.catalog.api.export import (
    _REGISTRY,
    EXPORT_ENTITY_TYPES,
    _relationship_namespaces,
)
from apps.catalog.cache import invalidate_response_cache
from apps.catalog.engine.aliases import discover_alias_types
from apps.catalog.models import MachineModel
from apps.provenance.test_factories import make_claim

from .conftest import SAMPLE_IMAGES

# Fields the public dump must never expose (internal/moderation/suppressed).
HIDDEN = frozenset(
    {
        "status",
        "ipdb_rating",
        "pinside_rating",
        "needs_review",
        "needs_review_notes",
        "extra_data",
    }
)


def _row(client, entity_plural: str, public_id: str) -> dict[str, Any]:
    resp = client.get(f"/api/export/{entity_plural}/")
    assert resp.status_code == 200
    return next(r for r in resp.json() if r["public_id"] == public_id)


class TestExportShape:
    def test_every_catalog_entity_has_a_route(self, client, machine_model):
        # 20 catalog entities, one blob route each.
        assert len(EXPORT_ENTITY_TYPES) == len(_REGISTRY)
        for plural in ("models", "manufacturers", "themes", "titles"):
            assert client.get(f"/api/export/{plural}/").status_code == 200

    def test_row_is_flat_and_slug_keyed(self, client, machine_model):
        row = _row(client, "models", machine_model.slug)
        assert row["name"] == machine_model.name
        # identity + freshness + description always present
        assert row["public_id"] == machine_model.slug
        assert "last_modified" in row
        assert set(row["description"]) == {"text", "attribution"}
        # FK emitted as a slug string (or None), never a nested object
        assert row["corporate_entity"] is None or isinstance(
            row["corporate_entity"], str
        )
        # M2M emitted as a list of slugs
        assert isinstance(row["themes"], list)
        assert isinstance(row["tags"], list)

    def test_consolidated_manufacturer_slug_on_row(self, client, machine_model):
        # The model links to the granular corporate entity, but the row also
        # carries the consolidated brand slug so consumers can key on it without
        # a second hop through /export/corporate-entities/.
        row = _row(client, "models", machine_model.slug)
        assert row["corporate_entity"] == "williams-electronics"
        assert row["manufacturer"] == "williams"

    def test_hidden_fields_never_exported(self, client, machine_model):
        row = _row(client, "models", machine_model.slug)
        for hidden in HIDDEN:
            assert hidden not in row, f"{hidden} leaked into the public export"

    def test_detail_grade_not_card(self, client, machine_model):
        # The card list (ModelListItemSchema) is name/slug/manufacturer/year/
        # thumbnail only; the export must carry the deeper fields.
        row = _row(client, "models", machine_model.slug)
        for deeper in ("description", "production_quantity", "opdb_id", "credits"):
            assert deeper in row


class TestExportRelations:
    def test_credits_are_person_role_pairs(
        self, client, machine_model, person, credit_roles
    ):
        from apps.catalog.models import Credit, CreditRole

        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(model=machine_model, person=person, role=role)
        invalidate_response_cache()
        row = _row(client, "models", machine_model.slug)
        assert {"person": person.slug, "role": "design"} in row["credits"]


class TestExportAbbreviations:
    """The bulk export is deliberately left claim-faithful — it serializes the
    raw materialized ``ModelAbbreviation`` rows, including values the Title also
    owns. (The model-detail endpoint dedups; the export does not.)"""

    def test_model_export_includes_title_overlapping_abbreviation(self, client, db):
        from apps.catalog.models import (
            ModelAbbreviation,
            Title,
            TitleAbbreviation,
        )

        title = Title.objects.create(name="Medieval Madness", slug="mm-title")
        pm = MachineModel.objects.create(name="MM", slug="mm-model", title=title)
        TitleAbbreviation.objects.create(title=title, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="TS4LE")
        invalidate_response_cache()

        row = _row(client, "models", pm.slug)
        assert sorted(row["abbreviations"]) == ["MM", "TS4LE"]


class TestExportStripsInlineCitations:
    def test_cite_marker_stripped_from_description(self, client, machine_model):
        # Guards the export_inline=False decoupling: after cite became a
        # public-id type, the strip must still drop its [[cite:id:N]] storage
        # marker from the public dump (not leak it, not emit a resolved cite).
        from apps.citation.models import CitationSource
        from apps.provenance.models import CitationInstance

        src = CitationSource.objects.create(name="Book", source_type="book")
        ci = CitationInstance.objects.create(citation_source=src)
        machine_model.description = f"A fact.[[cite:id:{ci.pk}]] More."
        machine_model.save()
        invalidate_response_cache()

        row = _row(client, "models", machine_model.slug)
        text = row["description"]["text"]
        assert "cite" not in text
        assert "[[" not in text
        assert text == "A fact. More."


class TestExportCache:
    def test_etag_and_conditional_304(self, client, machine_model):
        r1 = client.get("/api/export/models/")
        etag = r1["ETag"]
        assert etag
        r2 = client.get("/api/export/models/", HTTP_IF_NONE_MATCH=etag)
        assert r2.status_code == 304

    def test_mutation_invalidates(self, client, machine_model):
        before = client.get("/api/export/models/")
        assert before.status_code == 200
        machine_model.name = "Renamed Madness"
        machine_model.save()
        invalidate_response_cache()
        after = client.get("/api/export/models/")
        row = next(r for r in after.json() if r["public_id"] == machine_model.slug)
        assert row["name"] == "Renamed Madness"


class TestExportPerf:
    def test_bounded_queries(
        self, client, machine_model, another_model, django_assert_max_num_queries
    ):
        # Two models, bounded query budget — proves no per-row N+1. The budget
        # covers the base queryset + the fixed prefetches + the bulk link map.
        with django_assert_max_num_queries(20):
            resp = client.get("/api/export/models/")
        assert resp.status_code == 200
        assert len({r["public_id"] for r in resp.json()}) >= 2


class TestExportDriftGuard:
    # Snapshot of the model export's public field set. If a MachineModel field is
    # added/removed, this fails — forcing a conscious include/exclude decision
    # (fail-loud, not fail-open). Update deliberately when the surface changes.
    MODEL_FIELDS = frozenset(
        {
            "public_id",
            "name",
            "last_modified",
            "description",
            # claim scalars + FKs
            "year",
            "month",
            "player_count",
            "flipper_count",
            "production_quantity",
            "ipdb_id",
            "opdb_id",
            "pinside_id",
            "title",
            "variant_of",
            "converted_from",
            "remake_of",
            "corporate_entity",
            "system",
            "technology_generation",
            "technology_subgeneration",
            "display_type",
            "display_subtype",
            "cabinet",
            "game_format",
            "production_status",
            # derived: consolidated brand slug (corporate_entity -> manufacturer)
            "manufacturer",
            # media
            "thumbnail_url",
            "hero_image_url",
            "image_attribution",
            # relations
            "themes",
            "tags",
            "reward_types",
            "gameplay_features",
            "abbreviations",
            "credits",
        }
    )

    def test_model_field_set_is_pinned(self, client, machine_model):
        row = _row(client, "models", machine_model.slug)
        assert set(row) == self.MODEL_FIELDS

    def test_model_relationship_claims_are_covered(self):
        # Every claim-relationship namespace registered for MachineModel must be
        # served by a declared relation (media handled separately via media URLs;
        # gameplay_feature count is intentionally flattened to slugs).
        spec = next(s for s in _REGISTRY.values() if s.model is MachineModel)
        namespaces = _relationship_namespaces(MachineModel)
        covered = {
            "credit": "credits",
            "theme": "themes",
            "tag": "tags",
            "reward_type": "reward_types",
            "gameplay_feature": "gameplay_features",
            "abbreviation": "abbreviations",
        }
        for ns in namespaces - {"media_attachment"}:
            assert ns in covered, f"relationship namespace {ns!r} not covered"
            assert covered[ns] in spec.relations


class TestExportDerivedFields:
    def test_title_first_model_derivation(self, client, machine_model):
        # machine_model: a 1997 Williams model under "medieval-madness-title".
        row = _row(client, "titles", machine_model.title.slug)
        assert row["year"] == 1997
        assert row["manufacturer"] == "williams"

    def test_manufacturer_aggregates(self, client, machine_model):
        row = _row(client, "manufacturers", "williams")
        assert row["model_count"] == 1
        assert row["year_of_first_model"] == 1997
        assert row["year_of_last_model"] == 1997
        # No operating_status claim on the entity → defaults to "unknown".
        assert row["operating_status"] == "unknown"
        # The renamed fields fully replace the old lifespan-derived names.
        assert "year_min" not in row
        assert "year_max" not in row

    def test_manufacturer_operating_status_rolls_up(
        self, client, machine_model, williams_entity, source
    ):
        from apps.catalog.resolve import resolve_entity

        make_claim(williams_entity, "operating_status", "ongoing", source=source)
        resolve_entity(williams_entity)
        invalidate_response_cache()
        row = _row(client, "manufacturers", "williams")
        assert row["operating_status"] == "ongoing"

    def test_manufacturer_operating_status_precedence(
        self, client, manufacturer, williams_entity
    ):
        # The export rolls up in SQL (a Case/When subquery), independently of the
        # Python OperatingStatus.rollup; pin its precedence on the discriminating
        # multi-entity cases.
        from apps.catalog.models import CorporateEntity

        second = CorporateEntity.objects.create(
            name="Williams Later", slug="williams-later", manufacturer=manufacturer
        )

        def rollup(first: str, other: str) -> str:
            CorporateEntity.objects.filter(pk=williams_entity.pk).update(
                operating_status=first
            )
            CorporateEntity.objects.filter(pk=second.pk).update(operating_status=other)
            invalidate_response_cache()
            return str(_row(client, "manufacturers", "williams")["operating_status"])

        # ENDED only when every entity is known-ended; UNKNOWN outranks it.
        assert rollup("ended", "unknown") == "unknown"
        # ONGOING wins over everything, regardless of entity order.
        assert rollup("ended", "ongoing") == "ongoing"
        # All known-ended → ENDED.
        assert rollup("ended", "ended") == "ended"

    def test_corporate_entity_production_span(self, client, machine_model):
        row = _row(client, "corporate-entities", "williams-electronics")
        assert row["year_of_first_model"] == 1997
        assert row["year_of_last_model"] == 1997
        # operating_status is a real column → auto-exported as its wire value.
        assert row["operating_status"] == "unknown"
        # Legacy corporate-lifespan columns are dropped from the export.
        assert "year_start" not in row
        assert "year_end" not in row


class TestExportMediaGate:
    def test_image_url_gated_by_display_policy(self, client, machine_model):
        # A third-party image with an unknown/low permissiveness rank.
        machine_model.extra_data = {
            "opdb.images": SAMPLE_IMAGES,
            "opdb.images.__permissiveness_rank": 5,
        }
        machine_model.save()
        with override_config(CONTENT_DISPLAY_POLICY="licensed-only"):
            invalidate_response_cache()
            assert _row(client, "models", machine_model.slug)["thumbnail_url"] is None
        with override_config(CONTENT_DISPLAY_POLICY="show-all"):
            invalidate_response_cache()
            assert (
                _row(client, "models", machine_model.slug)["thumbnail_url"] is not None
            )


class TestExportAggregatingPerf:
    def test_manufacturer_bounded_queries(
        self, client, machine_model, another_model, django_assert_max_num_queries
    ):
        # The aggregating entity (Count/Min/Max annotations) must not N+1 either.
        with django_assert_max_num_queries(20):
            resp = client.get("/api/export/manufacturers/")
        assert resp.status_code == 200


class TestExportCompleteness:
    def test_alias_entities_export_aliases(self, client, machine_model):
        # Regression: aliases are derived from the registry, so an entity exports
        # an `aliases` field iff it's an AliasModel parent — no hand-list to drift.
        alias_parents = {at.parent_model for at in discover_alias_types()}
        for model, spec in _REGISTRY.items():
            assert (model in alias_parents) == ("aliases" in spec.relations), (
                f"{model.__name__}: alias-parent={model in alias_parents}, "
                f"exports-aliases={'aliases' in spec.relations}"
            )
        # And it surfaces on the wire (Williams manufacturer has an aliases list).
        assert _row(client, "manufacturers", "williams")["aliases"] == []

    def test_no_entity_leaks_internal_fields(self, client, machine_model):
        # Cross-entity net: the per-entity drift snapshot covers only MachineModel,
        # so guard every entity against leaking the known-internal claim fields.
        for spec in _REGISTRY.values():
            resp = client.get(f"/api/export/{spec.model.entity_type_plural}/")
            assert resp.status_code == 200
            for row in resp.json():
                leaked = HIDDEN & row.keys()
                assert not leaked, f"{spec.model.__name__} leaked {leaked}"


class TestExportRateLimit:
    @staticmethod
    def _limit_one(settings):
        # Squeeze the per-IP budget to 1 so the second request trips it (rather
        # than issuing 120). Overriding the setting exercises the real per-request
        # spec path; counters reset per test via the locmem-cache fixture.
        settings.EXPORT_RATELIMIT_IP = (1, 3600)

    def test_export_is_rate_limited_with_structured_429(
        self, client, machine_model, settings
    ):
        self._limit_one(settings)
        assert client.get("/api/export/models/").status_code == 200
        resp = client.get("/api/export/models/")
        assert resp.status_code == 429
        # Same wire shape as the rest of the app: Retry-After + structured body.
        assert resp["Retry-After"]
        assert resp.json()["detail"]["kind"] == "rate_limit"

    def test_spoofed_xff_cannot_rotate_the_bucket(
        self, client, machine_model, settings
    ):
        # The limit keys on the sanctioned IP (REMOTE_ADDR in tests, X-Real-IP via
        # Caddy in prod), never X-Forwarded-For — so rotating XFF can't dodge it.
        self._limit_one(settings)
        first = client.get("/api/export/models/", HTTP_X_FORWARDED_FOR="1.1.1.1")
        second = client.get("/api/export/models/", HTTP_X_FORWARDED_FOR="9.9.9.9")
        assert first.status_code == 200
        assert second.status_code == 429  # different XFF, same bucket

    def test_internal_api_is_not_rate_limited(self, client, machine_model):
        # The limiter lives in the export views only; internal routes are unmetered.
        # No squeeze needed — internal routes never read EXPORT_RATELIMIT_IP.
        assert client.get("/api/models/").status_code == 200
        assert client.get("/api/models/").status_code == 200
