"""Tests for the entity lifecycle status field."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.catalog.models import Manufacturer
from apps.claim_ingest.apply import apply_plan
from apps.claim_ingest.plan import (
    IngestPlan,
    PlannedClaimAssert,
    PlannedEntityCreate,
)
from apps.provenance.models import Claim, Source
from apps.provenance.validation import validate_claim_value

pytestmark = pytest.mark.django_db


@pytest.fixture
def test_source(db):
    return Source.objects.create(
        name="TestSource",
        slug="test-source",
        source_type="database",
        priority=50,
    )


# ── QuerySet .active() filtering ─────────────────────────────────


class TestActiveQuerySet:
    def test_active_entities_included(self):
        Manufacturer.objects.create(name="Active", slug="active", status="active")
        assert Manufacturer.objects.active().filter(slug="active").exists()

    def test_deleted_entities_excluded(self):
        Manufacturer.objects.create(name="Deleted", slug="deleted", status="deleted")
        assert not Manufacturer.objects.active().filter(slug="deleted").exists()

    def test_null_status_included(self):
        """Null status is treated as active (transitional for unconverted ingest)."""
        Manufacturer.objects.create(name="Legacy", slug="legacy", status=None)
        assert Manufacturer.objects.active().filter(slug="legacy").exists()

    def test_all_returns_everything(self):
        """Default .objects.all() returns all entities regardless of status."""
        Manufacturer.objects.create(name="A", slug="a", status="active")
        Manufacturer.objects.create(name="D", slug="d", status="deleted")
        Manufacturer.objects.create(name="N", slug="n", status=None)
        assert Manufacturer.objects.count() == 3

    def test_active_chaining(self):
        """.active() chains with other queryset methods."""
        Manufacturer.objects.create(name="Keep", slug="keep", status="active")
        Manufacturer.objects.create(name="Drop", slug="drop", status="deleted")
        qs = Manufacturer.objects.active().filter(name="Keep")
        assert qs.count() == 1
        first = qs.first()
        assert first is not None
        assert first.slug == "keep"


# ── Apply layer status='active' enforcement ──────────────────────


class TestApplyStatusEnforcement:
    def test_missing_status_in_kwargs_raises(self, test_source):
        """Entity creation without status='active' in kwargs is rejected."""
        plan = IngestPlan(
            source=test_source,
            input_fingerprint="fp-1",
            patch_id="fp-1",
            entities=[
                PlannedEntityCreate(
                    model_class=Manufacturer,
                    kwargs={"name": "Bally", "slug": "bally"},
                    handle="bally",
                ),
            ],
            assertions=[
                PlannedClaimAssert(
                    field_name="name", value="Bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="slug", value="bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="status", value="active", handle="bally", entry_index=0
                ),
            ],
        )
        with pytest.raises(ValueError, match="status='active'"):
            apply_plan(plan)

    def test_wrong_status_value_in_kwargs_raises(self, test_source):
        """Entity creation with status='deleted' in kwargs is rejected."""
        plan = IngestPlan(
            source=test_source,
            input_fingerprint="fp-1",
            patch_id="fp-1",
            entities=[
                PlannedEntityCreate(
                    model_class=Manufacturer,
                    kwargs={"name": "Bally", "slug": "bally", "status": "deleted"},
                    handle="bally",
                ),
            ],
            assertions=[
                PlannedClaimAssert(
                    field_name="name", value="Bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="slug", value="bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="status", value="deleted", handle="bally", entry_index=0
                ),
            ],
        )
        with pytest.raises(ValueError, match="status='active'"):
            apply_plan(plan)

    def test_valid_status_passes(self, test_source):
        """Entity creation with status='active' succeeds."""
        plan = IngestPlan(
            source=test_source,
            input_fingerprint="fp-1",
            patch_id="fp-1",
            entities=[
                PlannedEntityCreate(
                    model_class=Manufacturer,
                    kwargs={"name": "Bally", "slug": "bally", "status": "active"},
                    handle="bally",
                ),
            ],
            assertions=[
                PlannedClaimAssert(
                    field_name="name", value="Bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="slug", value="bally", handle="bally", entry_index=0
                ),
                PlannedClaimAssert(
                    field_name="status", value="active", handle="bally", entry_index=0
                ),
            ],
        )
        report = apply_plan(plan)
        assert report.records_created == 1
        mfr = Manufacturer.objects.get(slug="bally")
        assert mfr.status == "active"


# ── Choices validation at claim boundary ─────────────────────────


class TestChoicesValidation:
    def test_valid_status_passes_validation(self):
        value = validate_claim_value("status", "active", Manufacturer)
        assert value == "active"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError, match="not a valid choice"):
            validate_claim_value("status", "bogus", Manufacturer)

    def test_empty_status_passes(self):
        """Empty string is allowed (nullable field, resolver handles it)."""
        # Empty values skip the to_python/validators block entirely.
        value = validate_claim_value("status", "", Manufacturer)
        assert value == ""


# ── Resolution ───────────────────────────────────────────────────


class TestStatusResolution:
    def test_status_resolved_from_claim(self, test_source):
        """Status field is resolved from claims like any other scalar."""
        mfr = Manufacturer.objects.create(name="Bally", slug="bally")
        Claim.objects.assert_claim(mfr, "status", "active", source=test_source)

        from apps.catalog.resolve._entities import resolve_all_entities

        resolve_all_entities(Manufacturer, object_ids={mfr.pk})
        mfr.refresh_from_db()
        assert mfr.status == "active"

    def test_status_resets_to_null_when_no_claim(self):
        """Without a status claim, resolution resets status to null."""
        mfr = Manufacturer.objects.create(name="Bally", slug="bally", status="active")
        # No claims exist — resolution resets to default (None for nullable).
        from apps.catalog.resolve._entities import resolve_all_entities

        resolve_all_entities(Manufacturer, object_ids={mfr.pk})
        mfr.refresh_from_db()
        assert mfr.status is None


# ── CheckConstraint ──────────────────────────────────────────────


class TestStatusConstraint:
    def test_valid_status_accepted(self):
        mfr = Manufacturer(name="Test", slug="test-ok", status="active")
        mfr.full_clean()  # Should not raise.

    def test_invalid_status_rejected_by_db(self):
        """DB constraint rejects invalid status values."""
        # Raw SQL bypasses Python validation — only DB constraint catches it.
        from django.db import connection

        Manufacturer.objects.create(name="Test", slug="test-bad", status="active")
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                "UPDATE catalog_manufacturer SET status = 'bogus' "
                "WHERE slug = 'test-bad'"
            )
