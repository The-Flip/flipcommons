"""Tests for IngestRun model and its integration with ChangeSet and Claim."""

import pytest
from django.utils import timezone

from apps.catalog.models import Manufacturer
from apps.provenance.models import ChangeSet, IngestRun
from apps.provenance.test_factories import (
    ingest_changeset,
    make_claim,
    make_ingest_source,
    user_changeset,
)


@pytest.fixture
def source(db):
    return make_ingest_source(name="TestSource", slug="test-source", priority=10)


@pytest.fixture
def mfr(db):
    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.mark.django_db
class TestIngestRunModel:
    def test_create_with_all_fields(self, source):
        now = timezone.now()
        run = IngestRun.objects.create(
            source=source,
            finished_at=now,
            input_fingerprint="test-fingerprint",
            status=IngestRun.Status.SUCCESS,
            records_parsed=100,
            records_matched=95,
            records_created=5,
            claims_asserted=200,
            claims_retracted=3,
            claims_rejected=2,
            warnings=["minor issue"],
            errors=[],
        )
        assert run.pk is not None
        assert run.source == source
        assert run.started_at is not None
        assert run.status == "success"
        assert run.records_parsed == 100
        assert run.records_matched == 95
        assert run.records_created == 5
        assert run.claims_asserted == 200
        assert run.claims_retracted == 3
        assert run.claims_rejected == 2
        assert run.input_fingerprint == "test-fingerprint"
        assert run.warnings == ["minor issue"]
        assert run.errors == []

    def test_defaults(self, source):
        run = IngestRun.objects.create(
            source=source,
            input_fingerprint="sha256:abc",
        )
        assert run.started_at is not None
        assert run.finished_at is None
        assert run.status == "running"
        assert run.records_parsed == 0
        assert run.records_matched == 0
        assert run.records_created == 0
        assert run.claims_asserted == 0
        assert run.claims_retracted == 0
        assert run.claims_rejected == 0
        assert run.warnings == []
        assert run.errors == []

    def test_str(self, source):
        from django.utils import timezone

        run = IngestRun.objects.create(
            source=source,
            input_fingerprint="sha256:abc",
            status=IngestRun.Status.FAILED,
            finished_at=timezone.now(),
        )
        assert "TestSource" in str(run)
        assert "failed" in str(run)

    def test_status_constraint_rejects_invalid(self, source):
        """DB-level CHECK constraint rejects invalid status values."""
        from django.db import IntegrityError, connection

        run = IngestRun.objects.create(
            source=source,
            input_fingerprint="sha256:abc",
        )
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                "UPDATE provenance_ingestrun SET status = %s WHERE id = %s",
                ["bogus", run.pk],
            )

    def test_negative_count_rejected(self, source):
        """DB-level CHECK constraint rejects negative count values."""
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            IngestRun.objects.create(
                source=source,
                input_fingerprint="sha256:abc",
                records_parsed=-1,
            )

    def test_input_fingerprint_required(self, source):
        """input_fingerprint is NOT NULL with no default — omitting it is an error."""
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            IngestRun.objects.create(source=source)


@pytest.mark.django_db
class TestChangeSetIngestRunFK:
    def test_changeset_linked_to_ingest_run(self, source):
        run = IngestRun.objects.create(
            source=source,
            input_fingerprint="sha256:abc",
        )
        cs = ingest_changeset(run)
        assert cs.ingest_run == run
        assert ChangeSet.objects.filter(ingest_run=run).count() == 1

    def test_changeset_without_ingest_run(self):
        from apps.accounts.test_factories import make_user

        user = make_user(email="editor@example.com")
        cs = user_changeset(user)
        assert cs.ingest_run is None

    def test_delete_run_blocked_by_changesets(self, source):
        """PROTECT prevents deleting an IngestRun that has ChangeSets."""
        from django.db.models import ProtectedError

        run = IngestRun.objects.create(
            source=source,
            input_fingerprint="sha256:abc",
        )
        ingest_changeset(run)
        with pytest.raises(ProtectedError):
            run.delete()


@pytest.mark.django_db
class TestClaimRetractedByChangeset:
    def test_retracted_by_changeset_set(self, source, mfr):
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        claim = make_claim(mfr, "name", "Williams", ingest_source=source)
        cs = ingest_changeset(run)
        claim.retracted_by_changeset = cs
        claim.is_active = False
        claim.save()

        claim.refresh_from_db()
        assert claim.retracted_by_changeset == cs
        assert claim.is_active is False
        assert cs.retracted_claims.count() == 1

    def test_retracted_by_changeset_null_by_default(self, source, mfr):
        claim = make_claim(mfr, "name", "Williams", ingest_source=source)
        assert claim.retracted_by_changeset is None

    def test_delete_changeset_blocked_by_retracted_claims(self, source, mfr):
        """PROTECT prevents deleting a ChangeSet referenced by retracted claims."""
        from django.db.models import ProtectedError

        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:ret")
        claim = make_claim(mfr, "name", "Williams", ingest_source=source)
        cs = ingest_changeset(run)
        claim.retracted_by_changeset = cs
        claim.is_active = False
        claim.save()

        with pytest.raises(ProtectedError):
            cs.delete()
