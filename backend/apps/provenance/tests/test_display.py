"""Tests for the claim-value display engine in apps.provenance.display."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.test_factories import make_user
from apps.catalog.models import (
    CreditRole,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    Person,
    Theme,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.display import (
    ClaimDisplayContext,
    FieldValue,
    FkRef,
    build_display_value,
    claim_value,
    resolve_display_context,
    resolve_labels,
)
from apps.provenance.schemas import (
    ClaimDisplayIdentityPartSchema,
    ClaimDisplayQualifierPartSchema,
    ClaimDisplayValueSchema,
    MarkdownClaimDisplaySchema,
)
from apps.provenance.test_factories import make_claim

# Any ClaimControlledModel works for relationship/scalar dispatch: the display
# kind is derived from field_name + value, not from this model. Direct-FK and
# markdown dispatch DO read the model (concrete FK fields / MarkdownField set),
# so those tests pass the real subject model.
_MODEL = MachineModel


def _ctx(*items: FieldValue) -> ClaimDisplayContext:
    """Build a display context from explicit (field, value) references."""
    return resolve_display_context(items)


def _identity(parts: list[tuple[str, str]]) -> list[ClaimDisplayIdentityPartSchema]:
    # Helper for resolved-state identity parts. Failure-case tests construct
    # ClaimDisplayIdentityPartSchema directly with state="deleted" / "missing".
    return [
        ClaimDisplayIdentityPartSchema(key=k, label=v, state="resolved")
        for k, v in parts
    ]


def _qualifiers(
    parts: list[tuple[str, bool | int | str | None]],
) -> list[ClaimDisplayQualifierPartSchema]:
    return [ClaimDisplayQualifierPartSchema(key=k, value=v) for k, v in parts]


@pytest.mark.django_db
class TestBuildDisplayValue:
    def test_credit_emits_two_identity_parts_in_declaration_order(self):
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        role = CreditRole.objects.create(name="Art", slug="art")
        value = {"person": person.pk, "role": role.pk, "exists": True}

        ctx = _ctx(FieldValue("credit", value, _MODEL))
        assert build_display_value(
            _MODEL, "credit", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("person", "Pat Lawlor"), ("role", "Art")]),
            qualifiers=[],
        )

    def test_credit_with_deleted_targets_emits_deleted_state(self):
        # FK rows deleted between claim creation and history rendering —
        # a legitimate runtime condition. ``state="deleted"`` lets the
        # frontend render this case however it wants; ``label`` is null
        # because the backend doesn't choose presentation.
        value = {"person": 999, "role": 888, "exists": True}
        ctx = _ctx(FieldValue("credit", value, _MODEL))
        assert build_display_value(
            _MODEL, "credit", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=[
                ClaimDisplayIdentityPartSchema(
                    key="person", label=None, state="deleted"
                ),
                ClaimDisplayIdentityPartSchema(key="role", label=None, state="deleted"),
            ],
            qualifiers=[],
        )

    def test_corrupt_pk_type_degrades_to_missing_without_crashing(self):
        # Validation rule 5 rejects wrong-type FK values at write time, so
        # this shape shouldn't exist. If a stale row / bypassed ingest
        # source slips one through, the display engine must not 500 the
        # whole page — log, emit state="missing", carry on.
        value = {"person": "not-an-int", "role": 7, "exists": True}
        ctx = _ctx(FieldValue("credit", value, _MODEL))
        result = build_display_value(_MODEL, "credit", value, ctx)
        assert result is not None
        assert isinstance(result, ClaimDisplayValueSchema)
        person_part = next(p for p in result.identity if p.key == "person")
        assert person_part.state == "missing"
        assert person_part.label is None

    def test_gameplay_feature_emits_count_qualifier_when_present(self):
        feat = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        value = {"gameplay_feature": feat.pk, "count": 3, "exists": True}
        ctx = _ctx(FieldValue("gameplay_feature", value, _MODEL))
        # Backend always emits the qualifier when the key is present in the
        # claim dict — including count==1. The frontend's per-qualifier rule
        # decides whether to render ``×N`` (only when N > 1). Wire format
        # stays data-faithful.
        assert build_display_value(
            _MODEL, "gameplay_feature", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("gameplay_feature", "Multiball")]),
            qualifiers=_qualifiers([("count", 3)]),
        )

    def test_gameplay_feature_count_one_still_emits_qualifier(self):
        # Demonstrates the backend's "data-faithful" rule: the qualifier is
        # always emitted when present, with the raw value. The decision to
        # hide ``count == 1`` belongs on the frontend.
        feat = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        value = {"gameplay_feature": feat.pk, "count": 1, "exists": True}
        ctx = _ctx(FieldValue("gameplay_feature", value, _MODEL))
        assert build_display_value(
            _MODEL, "gameplay_feature", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("gameplay_feature", "Multiball")]),
            qualifiers=_qualifiers([("count", 1)]),
        )

    def test_gameplay_feature_omits_count_qualifier_when_missing(self):
        feat = GameplayFeature.objects.create(name="Multiball", slug="multiball")
        value = {"gameplay_feature": feat.pk, "exists": True}
        ctx = _ctx(FieldValue("gameplay_feature", value, _MODEL))
        # Absent key → no qualifier emitted. Distinct from count==0.
        assert build_display_value(
            _MODEL, "gameplay_feature", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("gameplay_feature", "Multiball")]),
            qualifiers=[],
        )

    def test_theme_emits_single_identity_part(self):
        theme = Theme.objects.create(name="Sci-Fi", slug="sci-fi")
        value = {"theme": theme.pk, "exists": True}
        ctx = _ctx(FieldValue("theme", value, _MODEL))
        assert build_display_value(
            _MODEL, "theme", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("theme", "Sci-Fi")]),
            qualifiers=[],
        )

    def test_abbreviation_emits_scalar_identity(self):
        value = {"value": "DW", "exists": True}
        ctx = _ctx(FieldValue("abbreviation", value, _MODEL))
        assert build_display_value(
            _MODEL, "abbreviation", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("value", "DW")]),
            qualifiers=[],
        )

    def test_bare_marker_emits_missing_state(self):
        # Validation rule 4 (required identity keys) shouldn't allow this
        # shape to reach build_display_value. If it ever does — e.g. a
        # stale row, a fixture, or an ingest source that skipped validation
        # — surface ``state="missing"`` so the frontend can render a
        # placeholder, and log loudly so the integrity issue is observable.
        ctx = _ctx()
        assert build_display_value(_MODEL, "credit", {"exists": False}, ctx) == (
            ClaimDisplayValueSchema(
                identity=[
                    ClaimDisplayIdentityPartSchema(
                        key="person", label=None, state="missing"
                    ),
                    ClaimDisplayIdentityPartSchema(
                        key="role", label=None, state="missing"
                    ),
                ],
                qualifiers=[],
            )
        )
        assert build_display_value(_MODEL, "theme", {"exists": False}, ctx) == (
            ClaimDisplayValueSchema(
                identity=[
                    ClaimDisplayIdentityPartSchema(
                        key="theme", label=None, state="missing"
                    )
                ],
                qualifiers=[],
            )
        )
        assert build_display_value(_MODEL, "abbreviation", {"exists": False}, ctx) == (
            ClaimDisplayValueSchema(
                identity=[
                    ClaimDisplayIdentityPartSchema(
                        key="value", label=None, state="missing"
                    )
                ],
                qualifiers=[],
            )
        )
        assert build_display_value(_MODEL, "person_alias", {"exists": False}, ctx) == (
            ClaimDisplayValueSchema(
                identity=[
                    ClaimDisplayIdentityPartSchema(
                        key="alias_value", label=None, state="missing"
                    )
                ],
                qualifiers=[],
            )
        )

    def test_alias_uses_display_key_override_when_present(self):
        # Load-bearing assertion: the backend chose the override (alias_display)
        # for the identity slot's ``label``, but kept the identity key name
        # ``alias_value`` so the wire format is self-describing.
        value = {
            "alias_value": "the patster",
            "alias_display": "The Patster",
            "exists": True,
        }
        ctx = _ctx(FieldValue("person_alias", value, _MODEL))
        assert build_display_value(
            _MODEL, "person_alias", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("alias_value", "The Patster")]),
            qualifiers=[],
        )

    def test_alias_falls_back_to_canonical_when_display_missing(self):
        value = {"alias_value": "the patster", "exists": True}
        ctx = _ctx(FieldValue("person_alias", value, _MODEL))
        assert build_display_value(
            _MODEL, "person_alias", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("alias_value", "the patster")]),
            qualifiers=[],
        )

    def test_alias_falls_back_to_canonical_when_display_empty(self):
        # Empty string override → fall through to canonical identity.
        # Mirrors the historical ``val.get("alias_display") or alias_val``.
        value = {"alias_value": "the patster", "alias_display": "", "exists": True}
        ctx = _ctx(FieldValue("person_alias", value, _MODEL))
        assert build_display_value(
            _MODEL, "person_alias", value, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("alias_value", "the patster")]),
            qualifiers=[],
        )

    def test_alias_display_key_target_is_not_also_emitted_as_qualifier(self):
        # The ``alias_display`` spec is named by ``alias_value.display_key``;
        # it MUST NOT also appear in the qualifiers list. Otherwise the
        # frontend would render the value twice.
        value = {
            "alias_value": "the patster",
            "alias_display": "The Patster",
            "exists": True,
        }
        ctx = _ctx(FieldValue("person_alias", value, _MODEL))
        result = build_display_value(_MODEL, "person_alias", value, ctx)
        assert result is not None
        assert isinstance(result, ClaimDisplayValueSchema)
        assert all(q.key != "alias_display" for q in result.qualifiers)

    def test_media_attachment_emits_identity_and_qualifiers(self):
        # Exercises the multi-qualifier case: FK identity + str qualifier
        # (category) + bool qualifier (is_primary, with bool/int distinction).
        # No need to materialize a real MediaAsset — the missing-target
        # ``<deleted>`` fallback is sufficient to exercise the engine.
        value = {
            "media_asset": 42,
            "category": "flyer",
            "is_primary": True,
            "exists": True,
        }
        ctx = _ctx()
        result = build_display_value(_MODEL, "media_attachment", value, ctx)
        assert result is not None
        assert isinstance(result, ClaimDisplayValueSchema)
        # pk=42 is synthetic / unresolved → state="deleted".
        assert result.identity == [
            ClaimDisplayIdentityPartSchema(
                key="media_asset", label=None, state="deleted"
            )
        ]
        # Declaration order: category before is_primary.
        assert result.qualifiers == _qualifiers(
            [("category", "flyer"), ("is_primary", True)]
        )

    def test_media_attachment_emits_falsy_qualifiers_when_present(self):
        # Backend is data-faithful: ``is_primary: false`` and an empty
        # category are emitted with their raw values. The frontend decides
        # whether to hide them.
        value = {
            "media_asset": 42,
            "category": "",
            "is_primary": False,
            "exists": True,
        }
        ctx = _ctx()
        result = build_display_value(_MODEL, "media_attachment", value, ctx)
        assert result is not None
        assert isinstance(result, ClaimDisplayValueSchema)
        assert result.qualifiers == _qualifiers(
            [("category", ""), ("is_primary", False)]
        )

    def test_preserves_bool_through_pydantic_union(self):
        # Guards against Pydantic v2 coercing True → 1 because bool is an int
        # subclass. ClaimDisplayQualifierPartSchema.value declares bool before int
        # so this round-trip should preserve the type.
        value = {"media_asset": 42, "is_primary": True, "exists": True}
        ctx = _ctx()
        result = build_display_value(_MODEL, "media_attachment", value, ctx)
        assert result is not None
        assert isinstance(result, ClaimDisplayValueSchema)
        primary = next(q for q in result.qualifiers if q.key == "is_primary")
        assert primary.value is True
        assert type(primary.value) is bool

    def test_unknown_namespace_returns_none(self):
        # Non-FK scalar claims (year is an IntegerField, not a namespace or
        # FK) fall through — frontend renders the raw scalar.
        ctx = _ctx()
        assert build_display_value(_MODEL, "year", 1998, ctx) is None

    def test_non_dict_value_returns_none(self):
        ctx = _ctx()
        assert build_display_value(_MODEL, "credit", None, ctx) is None
        assert build_display_value(_MODEL, "credit", "string", ctx) is None


@pytest.mark.django_db
class TestDirectFkDisplay:
    """Direct FK claim values (target PKs) render as a single identity part."""

    def test_fk_pk_resolves_to_entity_label(self):
        from apps.catalog.models import TechnologyGeneration

        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        ctx = _ctx(FieldValue("technology_generation", ss.pk, _MODEL))
        assert build_display_value(
            _MODEL, "technology_generation", ss.pk, ctx
        ) == ClaimDisplayValueSchema(
            identity=_identity([("technology_generation", "Solid State")]),
            qualifiers=[],
        )

    def test_missing_target_renders_deleted_state(self):
        # A validated-then-hard-deleted target degrades, not 500s.
        ctx = _ctx(FieldValue("technology_generation", 999999, _MODEL))
        assert build_display_value(
            _MODEL, "technology_generation", 999999, ctx
        ) == ClaimDisplayValueSchema(
            identity=[
                ClaimDisplayIdentityPartSchema(
                    key="technology_generation", label=None, state="deleted"
                )
            ],
            qualifiers=[],
        )

    def test_clear_sentinels_return_none(self):
        # ""/None mean cleared — frontend renders its own empty state.
        ctx = _ctx()
        assert build_display_value(_MODEL, "technology_generation", "", ctx) is None
        assert build_display_value(_MODEL, "technology_generation", None, ctx) is None

    def test_bool_is_not_treated_as_fk_pk(self):
        # isinstance(True, int) is True; the dispatch must not resolve it.
        ctx = _ctx()
        assert build_display_value(_MODEL, "technology_generation", True, ctx) is None

    def test_resolve_labels_ignores_direct_fields_and_bare_markers(self):
        # Resolve over a mixed batch: a credit dict, a theme dict, a
        # direct-field scalar (year), and a bare retraction marker. The
        # resulting lookup should only know about the FKs that were
        # genuinely referenced.
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        role = CreditRole.objects.create(name="Art", slug="art")
        theme = Theme.objects.create(name="Sci-Fi", slug="sci-fi")
        labels = resolve_labels(
            [
                FieldValue(
                    "credit",
                    {"person": person.pk, "role": role.pk, "exists": True},
                    _MODEL,
                ),
                FieldValue("theme", {"theme": theme.pk, "exists": True}, _MODEL),
                FieldValue("year", 1998, _MODEL),
                FieldValue("credit", {"exists": False}, _MODEL),
            ]
        )
        assert labels.get(FkRef(Person, person.pk)) == "Pat Lawlor"
        assert labels.get(FkRef(CreditRole, role.pk)) == "Art"
        assert labels.get(FkRef(Theme, theme.pk)) == "Sci-Fi"
        # Pks that were never referenced return None.
        assert labels.get(FkRef(Person, 999)) is None


@pytest.mark.django_db
class TestMarkdownDisplay:
    """Markdown-field claim values render as authoring-form text."""

    def test_markdown_field_renders_authoring_form(self):
        # Storage-form [[manufacturer:id:N]] resolves to the slug authoring
        # form — what the editor shows, so the diff reads the same.
        man = Manufacturer.objects.create(name="Williams", slug="williams")
        value = f"Made by [[manufacturer:id:{man.pk}]] here."
        ctx = _ctx(FieldValue("description", value, _MODEL))
        result = build_display_value(Manufacturer, "description", value, ctx)
        assert result == MarkdownClaimDisplaySchema(
            text="Made by [[manufacturer:williams]] here."
        )

    def test_markdown_deleted_target_keeps_storage_form(self):
        # Broken link (target deleted) keeps storage form — same as the editor.
        value = "Gone [[manufacturer:id:999999]]."
        ctx = _ctx(FieldValue("description", value, _MODEL))
        result = build_display_value(Manufacturer, "description", value, ctx)
        assert result == MarkdownClaimDisplaySchema(
            text="Gone [[manufacturer:id:999999]]."
        )

    def test_empty_markdown_value_has_no_display(self):
        ctx = _ctx(FieldValue("description", "", _MODEL))
        assert build_display_value(Manufacturer, "description", "", ctx) is None

    def test_markdown_without_links_passes_through(self):
        value = "Just plain prose, no links."
        ctx = _ctx(FieldValue("description", value, _MODEL))
        result = build_display_value(Manufacturer, "description", value, ctx)
        assert result == MarkdownClaimDisplaySchema(text="Just plain prose, no links.")

    def test_edit_history_endpoint_renders_authoring_form(self, client):
        # End-to-end bug reproduction: before the fix the description diff
        # showed raw [[manufacturer:id:N]] storage form. A user edit authored
        # in [[manufacturer:slug]] form must round-trip back to that form in
        # the diff's display.text (raw stays storage form).
        user = make_user()
        pm = make_machine_model(name="MM", slug="mm-eh", year=1997)
        man = Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")

        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data=json.dumps(
                {"fields": {"description": "By [[manufacturer:gottlieb]]."}}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        client.logout()

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200

        descr = next(
            ch
            for cs in resp.json()
            for ch in cs["changes"]
            if ch["field_name"] == "description"
        )
        assert descr["new_value"]["display"] == {
            "kind": "markdown",
            "text": "By [[manufacturer:gottlieb]].",
        }
        # raw stays the stored value — provenance truth is untouched.
        assert descr["new_value"]["raw"] == f"By [[manufacturer:id:{man.pk}]]."


@pytest.mark.django_db
class TestClaimValue:
    def test_relationship_field_bundles_display(self):
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        role = CreditRole.objects.create(name="Art", slug="art")
        value = {"person": person.pk, "role": role.pk, "exists": True}

        ctx = _ctx(FieldValue("credit", value, _MODEL))
        bundled = claim_value(_MODEL, "credit", value, ctx)

        assert bundled.raw == value
        assert bundled.display == ClaimDisplayValueSchema(
            identity=_identity([("person", "Pat Lawlor"), ("role", "Art")]),
            qualifiers=[],
        )

    def test_markdown_field_bundles_authoring_text(self):
        man = Manufacturer.objects.create(name="Bally", slug="bally")
        value = f"By [[manufacturer:id:{man.pk}]]."
        ctx = _ctx(FieldValue("description", value, _MODEL))
        bundled = claim_value(Manufacturer, "description", value, ctx)

        # raw stays the stored value; display carries the authoring form.
        assert bundled.raw == value
        assert bundled.display == MarkdownClaimDisplaySchema(
            text="By [[manufacturer:bally]]."
        )

    def test_scalar_field_has_null_display(self):
        bundled = claim_value(_MODEL, "name", "Medieval Madness", _ctx())
        assert bundled.raw == "Medieval Madness"
        assert bundled.display is None

    def test_deleted_fk_target_emits_deleted_state(self):
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        role = CreditRole.objects.create(name="Art", slug="art")
        value = {"person": person.pk, "role": role.pk, "exists": True}

        person.delete()
        # Resolve after deletion to simulate a stale-but-stored FK pk.
        ctx = _ctx(FieldValue("credit", value, _MODEL))
        bundled = claim_value(_MODEL, "credit", value, ctx)

        assert bundled.display is not None
        assert isinstance(bundled.display, ClaimDisplayValueSchema)
        states = {part.key: part.state for part in bundled.display.identity}
        assert states["person"] == "deleted"
        assert states["role"] == "resolved"


# ---------------------------------------------------------------------------
# Query-count regression: FK label resolution must be batched. If a future
# change inlines ``str(instance)`` into per-row formatting, query count
# would scale with the number of distinct FK targets in history — this
# test pins it.
# ---------------------------------------------------------------------------


def _q(fn: Callable[[], object]) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


@pytest.mark.django_db
class TestQueryCountDoesNotScale:
    def test_credits_resolved_in_batched_queries(self, client, bootstrap_source):
        """Adding more credits must not add per-credit FK lookup queries.

        Failure mode this guards against: build_display_value calling
        ``str(instance)`` via a lazy FK fetch inside the per-row loop,
        producing one query per credit on top of the batched baseline.
        """
        user = make_user()
        pm = make_machine_model(name="MM", slug="mm-credits", year=1997)
        make_claim(pm, "name", "MM", ingest_source=bootstrap_source)
        CreditRole.objects.create(name="Design", slug="design")

        counter = 0

        def add_credits(n: int) -> None:
            # New Person each iteration → maximises distinct FK pks
            # build_display_value must resolve across the two measured fetches.
            nonlocal counter
            client.force_login(user)
            for _ in range(n):
                counter += 1
                Person.objects.create(
                    name=f"Person {counter}", slug=f"person-{counter}"
                )
                resp = client.patch(
                    f"/api/models/{pm.slug}/claims/",
                    data=json.dumps(
                        {
                            "credits": [
                                {"person_slug": f"person-{counter}", "role": "design"}
                            ]
                        }
                    ),
                    content_type="application/json",
                )
                assert resp.status_code == 200, (
                    f"seed PATCH failed with {resp.status_code}: {resp.content!r}"
                )

        add_credits(2)
        client.logout()
        url = f"/api/pages/edit-history/model/{pm.slug}/"
        base = _q(lambda: client.get(url))

        add_credits(18)
        client.logout()
        scaled = _q(lambda: client.get(url))

        assert scaled == base, (
            f"edit-history query count scales with credit count: {base} -> {scaled}. "
            f"build_display_value is likely resolving FK labels per-row "
            f"instead of via the batched resolve_labels() pass."
        )

    def test_description_wikilinks_resolved_in_batched_queries(self, client):
        """Adding more wikilinked description edits must not add per-edit
        id→slug lookup queries.

        Each edit is a *user* changeset, so the measured request renders N
        description diffs through ``build_display_value`` (old→new per
        changeset). Guards the markdown path against a regression that moves
        storage→authoring conversion into the per-row render: the batched
        ``resolve_wikilink_authoring`` must resolve all ids in one query per
        public-id link type, not convert per rendered row.
        """
        user = make_user()
        pm = make_machine_model(name="MM", slug="mm-descr", year=1997)

        counter = 0

        def add_description_edits(n: int) -> None:
            # Each edit cites a distinct manufacturer (authoring form, converted
            # to storage on save), so rendering must resolve many distinct ids.
            nonlocal counter
            client.force_login(user)
            for _ in range(n):
                counter += 1
                man = Manufacturer.objects.create(
                    name=f"Maker {counter}", slug=f"maker-{counter}"
                )
                resp = client.patch(
                    f"/api/models/{pm.slug}/claims/",
                    data=json.dumps(
                        {
                            "fields": {
                                "description": (
                                    f"Edit {counter} citing [[manufacturer:{man.slug}]]."
                                )
                            }
                        }
                    ),
                    content_type="application/json",
                )
                assert resp.status_code == 200, (
                    f"seed PATCH failed with {resp.status_code}: {resp.content!r}"
                )

        add_description_edits(2)
        client.logout()
        url = f"/api/pages/edit-history/model/{pm.slug}/"
        base = _q(lambda: client.get(url))

        add_description_edits(18)
        client.logout()
        scaled = _q(lambda: client.get(url))

        assert scaled == base, (
            f"edit-history query count scales with description edits: "
            f"{base} -> {scaled}. The markdown display path is likely "
            f"converting storage→authoring per rendered row instead of via the "
            f"batched resolve_wikilink_authoring() pass."
        )
