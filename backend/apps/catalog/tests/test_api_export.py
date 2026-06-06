"""Tests for the model-driven bulk-export API (``GET /api/export/<entity>/``)."""

from __future__ import annotations

from typing import Any

from constance.test import override_config

from apps.catalog._alias_registry import discover_alias_types
from apps.catalog.api.export import (
    _REGISTRY,
    EXPORT_ENTITY_TYPES,
    _relationship_namespaces,
)
from apps.catalog.cache import invalidate_all
from apps.catalog.models import MachineModel

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
        invalidate_all()
        row = _row(client, "models", machine_model.slug)
        assert {"person": person.slug, "role": "design"} in row["credits"]


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
        invalidate_all()
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
        assert row["year_min"] == 1997
        assert row["year_max"] == 1997


class TestExportMediaGate:
    def test_image_url_gated_by_display_policy(self, client, machine_model):
        # A third-party image with an unknown/low permissiveness rank.
        machine_model.extra_data = {
            "opdb.images": SAMPLE_IMAGES,
            "opdb.images.__permissiveness_rank": 5,
        }
        machine_model.save()
        with override_config(CONTENT_DISPLAY_POLICY="licensed-only"):
            invalidate_all()
            assert _row(client, "models", machine_model.slug)["thumbnail_url"] is None
        with override_config(CONTENT_DISPLAY_POLICY="show-all"):
            invalidate_all()
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
