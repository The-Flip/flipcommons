"""Tests for the apply layer framework (synthetic plans, no real source data)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.catalog.models import CorporateEntity, Manufacturer, Theme
from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.plan import (
    IngestPlan,
    PlannedClaimAssert,
    PlannedClaimRetract,
    PlannedEntityCreate,
)
from apps.provenance.models import ChangeSet, Claim, IngestRun
from apps.provenance.test_factories import make_ingest_source

pytestmark = pytest.mark.django_db


@pytest.fixture
def test_source(db):
    return make_ingest_source(
        name="TestSource",
        slug="test-source",
        source_type="database",
        priority=50,
    )


def _mfr_ct_id() -> int:
    return ContentType.objects.get_for_model(Manufacturer).pk


# Every apply_plan caller is now the data-patch front end, so test plans carry a
# patch_id and per-entry provenance. These factories default both: patch_id is
# keyed off the (per-call distinct) fingerprint so the ledger's per-patch_id
# uniqueness stays happy across multi-run tests, and entry_index defaults to a
# single entry. Tests that exercise entry grouping pass entry_index explicitly.
def _plan(**kwargs):
    kwargs.setdefault("patch_id", kwargs.get("input_fingerprint", "fp-test"))
    return IngestPlan(**kwargs)


def _assert(**kwargs):
    kwargs.setdefault("entry_index", 0)
    return PlannedClaimAssert(**kwargs)


def _retract(**kwargs):
    kwargs.setdefault("entry_index", 0)
    return PlannedClaimRetract(**kwargs)


# ── Test 1: Create entities + claims ───────────────────────────────


def test_create_entities_and_claims(test_source):
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Bally", "slug": "bally", "status": "active"},
                handle="bally",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Bally", handle="bally"),
            _assert(field_name="slug", value="bally", handle="bally"),
            _assert(field_name="status", value="active", handle="bally"),
            _assert(
                field_name="description",
                value="A pinball company",
                handle="bally",
            ),
        ],
    )
    report = apply_plan(plan)

    assert report.records_created == 1
    assert report.asserted == 4
    assert report.unchanged == 0

    mfr = Manufacturer.objects.get(slug="bally")
    assert mfr.name == "Bally"

    active_claims = Claim.objects.filter(actor=test_source.actor, is_active=True)
    assert active_claims.count() == 4

    run = IngestRun.objects.get(source=test_source)
    assert run.status == IngestRun.Status.SUCCESS
    assert run.records_created == 1
    assert run.claims_asserted == 4


# ── Test 2: Idempotency ───────────────────────────────────────────


def test_idempotency(test_source):
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = _mfr_ct_id()

    def _make_plan(fp):
        return _plan(
            source=test_source,
            input_fingerprint=fp,
            assertions=[
                _assert(
                    field_name="description",
                    value="A pinball company",
                    content_type_id=ct_id,
                    object_id=mfr.pk,
                ),
            ],
        )

    report1 = apply_plan(_make_plan("fp-1"))
    assert report1.asserted == 1
    assert report1.unchanged == 0

    claim_count_after_first = Claim.objects.filter(actor=test_source.actor).count()

    report2 = apply_plan(_make_plan("fp-2"))
    assert report2.asserted == 0
    assert report2.unchanged == 1
    assert report2.superseded == 0
    assert (
        Claim.objects.filter(actor=test_source.actor).count() == claim_count_after_first
    )


# ── Test 3: Explicit retract_claim ─────────────────────────────────


def test_explicit_retraction(test_source):
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = _mfr_ct_id()

    # Run 1: assert description.
    plan1 = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="Original",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
        ],
    )
    apply_plan(plan1)
    assert Claim.objects.filter(
        actor=test_source.actor,
        field_name="description",
        is_active=True,
    ).exists()

    # Run 2: retract that claim.
    plan2 = _plan(
        source=test_source,
        input_fingerprint="fp-2",
        retractions=[
            _retract(
                content_type_id=ct_id,
                object_id=mfr.pk,
                claim_key="description",
            ),
        ],
    )
    report2 = apply_plan(plan2)
    assert report2.retracted == 1

    claim = Claim.objects.get(actor=test_source.actor, field_name="description")
    assert claim.is_active is False
    assert claim.retracted_by_changeset is not None
    assert claim.retracted_by_changeset.ingest_run is not None
    assert claim.retracted_by_changeset.ingest_run.source == test_source


# ── Test 4: Invalid claim fails entire run ─────────────────────────


def test_invalid_claim_fails_run(test_source):
    theme = Theme.objects.create(name="Medieval", slug="medieval")
    ct_id = ContentType.objects.get_for_model(Theme).pk

    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="bogus_field",
                value="whatever",
                content_type_id=ct_id,
                object_id=theme.pk,
            ),
        ],
    )

    with pytest.raises(ValidationError):
        apply_plan(plan)

    run = IngestRun.objects.get(source=test_source)
    assert run.status == IngestRun.Status.FAILED
    assert run.claims_rejected == 1
    assert len(run.errors) > 0
    # Transaction rolled back — no claims persisted.
    assert Claim.objects.filter(actor=test_source.actor).count() == 0


# ── Test 5: Omitted field preserved (additive-only) ───────────────


def test_omitted_field_preserved(test_source):
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = _mfr_ct_id()

    # Run 1: assert description + website.
    plan1 = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="A company",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
            _assert(
                field_name="website",
                value="https://bally.com",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
        ],
    )
    apply_plan(plan1)

    # Run 2: assert only description (website omitted).
    plan2 = _plan(
        source=test_source,
        input_fingerprint="fp-2",
        assertions=[
            _assert(
                field_name="description",
                value="A company",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
        ],
    )
    apply_plan(plan2)

    # Website claim is still active — not retracted.
    website_claim = Claim.objects.get(
        actor=test_source.actor,
        field_name="website",
        is_active=True,
    )
    assert website_claim.value == "https://bally.com"


# ── Test 7: Failed apply (exception in resolve) ───────────────────


def test_failed_apply_ingest_run_survives(test_source):
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = _mfr_ct_id()

    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="A pinball company",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
        ],
    )

    # A resolve failure (here, the provenance bulk dispatch raising) must fail
    # the run and roll the transaction back.
    with (
        mock.patch(
            "apps.provenance.resolution.resolve_entities_bulk",
            side_effect=RuntimeError("Resolve failed!"),
        ),
        pytest.raises(RuntimeError, match="Resolve failed"),
    ):
        apply_plan(plan)

    run = IngestRun.objects.get(source=test_source)
    assert run.status == IngestRun.Status.FAILED
    assert "Resolve failed!" in run.errors[0]
    # Transaction rolled back — no claims persisted.
    assert Claim.objects.filter(actor=test_source.actor).count() == 0


# ── Test 8: ChangeSets per authoring entry ─────────────────────────


def test_changesets_per_entry(test_source):
    """ChangeSets group by ``entry_index``, not by entity.

    Two assertions in distinct entries (0, 1) → two ChangeSets, even though
    both target a Manufacturer — one ChangeSet per authoring entry.
    """
    mfr1 = Manufacturer.objects.create(name="Bally", slug="bally")
    mfr2 = Manufacturer.objects.create(name="Williams", slug="williams")
    ct_id = _mfr_ct_id()

    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="Company 1",
                content_type_id=ct_id,
                object_id=mfr1.pk,
                entry_index=0,
            ),
            _assert(
                field_name="description",
                value="Company 2",
                content_type_id=ct_id,
                object_id=mfr2.pk,
                entry_index=1,
            ),
        ],
    )
    report = apply_plan(plan)
    assert report.asserted == 2

    run = IngestRun.objects.get(source=test_source)
    assert ChangeSet.objects.filter(ingest_run=run).count() == 2

    # Each claim lands in its own entry's changeset.
    cs_ids = {
        c.changeset_id
        for c in Claim.objects.filter(actor=test_source.actor, is_active=True)
    }
    assert len(cs_ids) == 2


def test_one_entry_spans_multiple_entities(test_source):
    """A single entry touching several entities → one multi-entity ChangeSet.

    The cascade-delete shape: one authoring action is one undoable event, no
    matter how many entities it touches.
    """
    mfr1 = Manufacturer.objects.create(name="Bally", slug="bally")
    mfr2 = Manufacturer.objects.create(name="Williams", slug="williams")
    ct_id = _mfr_ct_id()

    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="Company 1",
                content_type_id=ct_id,
                object_id=mfr1.pk,
                entry_index=0,
            ),
            _assert(
                field_name="description",
                value="Company 2",
                content_type_id=ct_id,
                object_id=mfr2.pk,
                entry_index=0,
            ),
        ],
    )
    apply_plan(plan)

    run = IngestRun.objects.get(source=test_source)
    assert ChangeSet.objects.filter(ingest_run=run).count() == 1


# ── Test 9: Entity-claim consistency validation ────────────────────


def test_entity_claim_consistency(test_source):
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Bally", "slug": "bally", "status": "active"},
                handle="bally",
            ),
        ],
        assertions=[
            # Slug + status assertions present, but name assertion is missing.
            _assert(
                field_name="slug",
                value="bally",
                handle="bally",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="bally",
            ),
        ],
    )

    with pytest.raises(ValueError, match="name"):
        apply_plan(plan)

    # Structural validation runs before IngestRun creation — no run record.
    assert not IngestRun.objects.filter(source=test_source).exists()
    assert not Manufacturer.objects.filter(slug="bally").exists()


# ── Test 10: Supersede (value change) ──────────────────────────────


def test_supersede_on_value_change(test_source):
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = _mfr_ct_id()

    # Run 1: assert description.
    plan1 = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="Old value",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
        ],
    )
    report1 = apply_plan(plan1)
    assert report1.asserted == 1
    old_claim = Claim.objects.get(
        actor=test_source.actor,
        field_name="description",
        is_active=True,
    )

    # Run 2: assert different value for same field.
    plan2 = _plan(
        source=test_source,
        input_fingerprint="fp-2",
        assertions=[
            _assert(
                field_name="description",
                value="New value",
                content_type_id=ct_id,
                object_id=mfr.pk,
            ),
        ],
    )
    report2 = apply_plan(plan2)
    assert report2.asserted == 1
    assert report2.superseded == 1
    assert report2.unchanged == 0

    # Old claim deactivated, new one active.
    old_claim.refresh_from_db()
    assert old_claim.is_active is False
    new_claim = Claim.objects.get(
        actor=test_source.actor,
        field_name="description",
        is_active=True,
    )
    assert new_claim.value == "New value"
    assert new_claim.pk != old_claim.pk


# ── Test 11: Malformed assertion target ────────────────────────────


def test_unknown_handle_raises(test_source):
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="whatever",
                handle="nonexistent",
            ),
        ],
    )

    with pytest.raises(ValueError, match="unknown handle"):
        apply_plan(plan)


def test_missing_target_raises(test_source):
    """Assertion with neither handle nor content_type_id/object_id."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        assertions=[
            _assert(
                field_name="description",
                value="whatever",
            ),
        ],
    )

    with pytest.raises(ValueError, match="neither a handle nor"):
        apply_plan(plan)


# ── Test 12: Retraction warning for missing target ─────────────────


def test_retraction_warning_for_missing_target(test_source):
    mfr = Manufacturer.objects.create(name="Bally", slug="bally")
    ct_id = _mfr_ct_id()

    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        retractions=[
            _retract(
                content_type_id=ct_id,
                object_id=mfr.pk,
                claim_key="description",
            ),
        ],
    )
    report = apply_plan(plan)
    assert report.retracted == 0
    assert len(report.warnings) == 1
    assert "Retract target not found" in report.warnings[0]
    assert "description" in report.warnings[0]


# ── Test 13: Duplicate handle ──────────────────────────────────────


def test_duplicate_handle_raises(test_source):
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Bally", "slug": "bally", "status": "active"},
                handle="dupe",
            ),
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Williams", "slug": "williams", "status": "active"},
                handle="dupe",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Bally", handle="dupe"),
            _assert(field_name="slug", value="bally", handle="dupe"),
            _assert(field_name="status", value="active", handle="dupe"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate handle"):
        apply_plan(plan)


# ── Test 14: Malformed targets rejected ────────────────────────────


def test_rejects_missing_target(test_source):
    """An assertion with neither handle nor ct/obj fails structural validation."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-missing-target",
        assertions=[
            _assert(
                field_name="description",
                value="whatever",
            ),
        ],
    )

    with pytest.raises(ValueError, match="neither a handle nor"):
        apply_plan(plan)


# ── Test 15: Conflicting assertion target ──────────────────────────


def test_both_handle_and_target_raises(test_source):
    """Assertion with both handle and content_type_id/object_id is ambiguous."""
    ct_id = _mfr_ct_id()
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Bally", "slug": "bally", "status": "active"},
                handle="bally",
            ),
        ],
        assertions=[
            _assert(
                field_name="name",
                value="Bally",
                handle="bally",
                content_type_id=ct_id,
                object_id=999,
            ),
            _assert(
                field_name="slug",
                value="bally",
                handle="bally",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="bally",
            ),
        ],
    )

    with pytest.raises(ValueError, match=r"both a handle.*and content_type_id"):
        apply_plan(plan)


# ── Test 16: handle_refs resolves FK dependencies ────────────────


def test_handle_refs_resolves_fk(test_source):
    """CorporateEntity with handle_ref to a planned Manufacturer."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Williams", "slug": "williams", "status": "active"},
                handle="mfr-williams",
            ),
            PlannedEntityCreate(
                model_class=CorporateEntity,
                kwargs={
                    "name": "Williams Electronics",
                    "slug": "williams-electronics",
                    "status": "active",
                },
                handle="ce-williams",
                handle_refs={"manufacturer_id": "mfr-williams"},
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Williams", handle="mfr-williams"),
            _assert(field_name="slug", value="williams", handle="mfr-williams"),
            _assert(field_name="status", value="active", handle="mfr-williams"),
            _assert(
                field_name="name",
                value="Williams Electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="slug",
                value="williams-electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="ce-williams",
            ),
            _assert(
                field_name="manufacturer",
                value_ref="mfr-williams",
                handle="ce-williams",
            ),
        ],
    )
    report = apply_plan(plan)

    assert report.records_created == 2
    assert report.asserted == 7

    mfr = Manufacturer.objects.get(slug="williams")
    ce = CorporateEntity.objects.get(slug="williams-electronics")
    assert ce.manufacturer == mfr


# ── Test 17: handle_refs forward reference raises ────────────────


def test_handle_refs_forward_reference_raises(test_source):
    """handle_ref pointing to a handle that appears later is rejected."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=CorporateEntity,
                kwargs={
                    "name": "Williams Electronics",
                    "slug": "williams-electronics",
                    "status": "active",
                },
                handle="ce-williams",
                handle_refs={"manufacturer_id": "mfr-williams"},
            ),
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Williams", "slug": "williams", "status": "active"},
                handle="mfr-williams",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Williams", handle="mfr-williams"),
            _assert(field_name="slug", value="williams", handle="mfr-williams"),
            _assert(field_name="status", value="active", handle="mfr-williams"),
            _assert(
                field_name="name",
                value="Williams Electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="slug",
                value="williams-electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="ce-williams",
            ),
            _assert(
                field_name="manufacturer",
                value_ref="mfr-williams",
                handle="ce-williams",
            ),
        ],
    )

    with pytest.raises(ValueError, match="has not been seen yet"):
        apply_plan(plan)


# ── Test 18: handle_refs conflict with kwargs raises ─────────────


def test_handle_refs_kwarg_conflict_raises(test_source):
    """Same field in both kwargs and handle_refs is rejected."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Williams", "slug": "williams", "status": "active"},
                handle="mfr-williams",
            ),
            PlannedEntityCreate(
                model_class=CorporateEntity,
                kwargs={
                    "name": "Williams Electronics",
                    "slug": "williams-electronics",
                    "status": "active",
                    "manufacturer_id": 999,
                },
                handle="ce-williams",
                handle_refs={"manufacturer_id": "mfr-williams"},
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Williams", handle="mfr-williams"),
            _assert(field_name="slug", value="williams", handle="mfr-williams"),
            _assert(field_name="status", value="active", handle="mfr-williams"),
            _assert(
                field_name="name",
                value="Williams Electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="slug",
                value="williams-electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="ce-williams",
            ),
            _assert(
                field_name="manufacturer",
                value_ref="mfr-williams",
                handle="ce-williams",
            ),
        ],
    )

    with pytest.raises(ValueError, match="both kwargs and handle_refs"):
        apply_plan(plan)


# ── Test 19: handle_refs FK without matching claim assertion ──────


def test_handle_ref_without_claim_raises(test_source):
    """handle_ref sets a claim-controlled FK but no assertion exists for it."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Manufacturer,
                kwargs={"name": "Williams", "slug": "williams", "status": "active"},
                handle="mfr-williams",
            ),
            PlannedEntityCreate(
                model_class=CorporateEntity,
                kwargs={
                    "name": "Williams Electronics",
                    "slug": "williams-electronics",
                    "status": "active",
                },
                handle="ce-williams",
                handle_refs={"manufacturer_id": "mfr-williams"},
            ),
        ],
        assertions=[
            _assert(
                field_name="name",
                value="Williams",
                handle="mfr-williams",
            ),
            _assert(
                field_name="slug",
                value="williams",
                handle="mfr-williams",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="mfr-williams",
            ),
            _assert(
                field_name="name",
                value="Williams Electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="slug",
                value="williams-electronics",
                handle="ce-williams",
            ),
            _assert(
                field_name="status",
                value="active",
                handle="ce-williams",
            ),
            # No manufacturer assertion for ce-williams — should fail.
        ],
    )

    with pytest.raises(ValueError, match=r"manufacturer.*via handle_ref"):
        apply_plan(plan)


# ── Test 20: identity_refs resolves PK in relationship claim ──────


def test_identity_refs_resolves_pk(test_source):
    """Deferred relationship claim gets claim_key + value generated after handle resolution."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Theme,
                kwargs={"name": "Sports", "slug": "sports", "status": "active"},
                handle="theme:sports",
            ),
            PlannedEntityCreate(
                model_class=Theme,
                kwargs={"name": "Baseball", "slug": "baseball", "status": "active"},
                handle="theme:baseball",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Sports", handle="theme:sports"),
            _assert(field_name="slug", value="sports", handle="theme:sports"),
            _assert(field_name="status", value="active", handle="theme:sports"),
            _assert(field_name="name", value="Baseball", handle="theme:baseball"),
            _assert(field_name="slug", value="baseball", handle="theme:baseball"),
            _assert(field_name="status", value="active", handle="theme:baseball"),
            # Deferred: Baseball's parent is Sports (both planned).
            _assert(
                field_name="theme_parent",
                handle="theme:baseball",
                relationship_namespace="theme_parent",
                identity={},
                identity_refs={"parent": "theme:sports"},
            ),
        ],
    )
    report = apply_plan(plan)

    assert report.records_created == 2
    # 6 scalar claims + 1 relationship claim = 7
    assert report.asserted == 7

    sports = Theme.objects.get(slug="sports")
    baseball = Theme.objects.get(slug="baseball")

    # The relationship claim should have been resolved with the real PK.
    claim = Claim.objects.get(
        actor=test_source.actor,
        field_name="theme_parent",
        is_active=True,
    )
    assert claim.object_id == baseball.pk
    assert claim.value["parent"] == sports.pk
    assert claim.value["exists"] is True
    assert f"parent:{sports.pk}" in claim.claim_key


# ── Test 21: identity_refs with existing target ──────────────────


def test_identity_refs_with_existing_target(test_source):
    """Assertion targets existing entity by ct/obj but uses identity_refs for value."""
    existing_parent = Theme.objects.create(
        name="Sports", slug="sports", status="active"
    )
    ct_id = ContentType.objects.get_for_model(Theme).pk

    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Theme,
                kwargs={"name": "Baseball", "slug": "baseball", "status": "active"},
                handle="theme:baseball",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Baseball", handle="theme:baseball"),
            _assert(field_name="slug", value="baseball", handle="theme:baseball"),
            _assert(field_name="status", value="active", handle="theme:baseball"),
            # Existing Sports gets a theme_parent claim referencing planned Baseball.
            _assert(
                field_name="theme_parent",
                content_type_id=ct_id,
                object_id=existing_parent.pk,
                relationship_namespace="theme_parent",
                identity={},
                identity_refs={"parent": "theme:baseball"},
            ),
        ],
    )
    report = apply_plan(plan)

    assert report.records_created == 1
    assert report.asserted == 4  # 3 scalar + 1 relationship

    baseball = Theme.objects.get(slug="baseball")
    claim = Claim.objects.get(
        actor=test_source.actor,
        field_name="theme_parent",
        is_active=True,
    )
    assert claim.object_id == existing_parent.pk
    assert claim.value["parent"] == baseball.pk


# ── Test 22: unknown handle in identity_refs raises ──────────────


def test_identity_refs_unknown_handle_raises(test_source):
    """identity_ref referencing a non-existent handle is rejected."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Theme,
                kwargs={"name": "Sports", "slug": "sports", "status": "active"},
                handle="theme:sports",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Sports", handle="theme:sports"),
            _assert(field_name="slug", value="sports", handle="theme:sports"),
            _assert(field_name="status", value="active", handle="theme:sports"),
            _assert(
                field_name="theme_parent",
                handle="theme:sports",
                relationship_namespace="theme_parent",
                identity={},
                identity_refs={"parent": "theme:nonexistent"},
            ),
        ],
    )

    with pytest.raises(ValueError, match=r"identity_ref.*parent.*theme:nonexistent"):
        apply_plan(plan)


# ── Test 23: mutual exclusivity — claim_key + relationship_namespace ─


def test_identity_refs_mutual_exclusivity_raises(test_source):
    """Having both claim_key/value and relationship_namespace is rejected."""
    plan = _plan(
        source=test_source,
        input_fingerprint="fp-1",
        entities=[
            PlannedEntityCreate(
                model_class=Theme,
                kwargs={"name": "Sports", "slug": "sports", "status": "active"},
                handle="theme:sports",
            ),
        ],
        assertions=[
            _assert(field_name="name", value="Sports", handle="theme:sports"),
            _assert(field_name="slug", value="sports", handle="theme:sports"),
            _assert(field_name="status", value="active", handle="theme:sports"),
            _assert(
                field_name="theme_parent",
                handle="theme:sports",
                claim_key="theme_parent|parent:99",
                value={"parent": 99, "exists": True},
                relationship_namespace="theme_parent",
                identity={},
                identity_refs={"parent": "theme:sports"},
            ),
        ],
    )

    with pytest.raises(ValueError, match=r"both concrete.*and relationship_namespace"):
        apply_plan(plan)
