"""Tests for the ChangeSet model and its integration with Claim."""

import pytest
from django.db import IntegrityError

from apps.accounts.test_factories import make_user
from apps.catalog.models import Manufacturer
from apps.core.models import License
from apps.provenance.models import ChangeSet, IngestRun, Source
from apps.provenance.test_factories import make_claim


@pytest.fixture
def mfr(db):
    return Manufacturer.objects.create(name="Williams", slug="williams")


@pytest.fixture
def source(db):
    return Source.objects.create(name="TestSource", slug="test-source", priority=10)


@pytest.mark.django_db
class TestChangeSetModel:
    def test_create_changeset(self, user):
        cs = ChangeSet.objects.create(
            user=user, action="edit", note="Fixed description"
        )
        assert cs.pk is not None
        assert cs.user == user
        assert cs.note == "Fixed description"
        assert cs.created_at is not None

    def test_changeset_without_note(self, user):
        cs = ChangeSet.objects.create(user=user, action="edit")
        assert cs.note == ""

    def test_changeset_with_ingest_run(self, source):
        """ChangeSet with ingest_run (no user) is allowed."""
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        cs = ChangeSet.objects.create(ingest_run=run)
        assert cs.user is None
        assert cs.ingest_run == run


@pytest.mark.django_db
class TestChangeSetClaimGrouping:
    def test_claims_linked_to_changeset(self, user, mfr):
        cs = ChangeSet.objects.create(user=user, action="edit", note="Updated fields")
        c1 = make_claim(mfr, "name", "Williams Electronics", user=user, changeset=cs)
        c2 = make_claim(
            mfr, "description", "Pinball manufacturer", user=user, changeset=cs
        )
        assert c1.changeset == cs
        assert c2.changeset == cs
        assert set(cs.claims.values_list("pk", flat=True)) == {c1.pk, c2.pk}

    def test_user_claim_without_changeset_rejected(self, user, mfr):
        """A user-attributed claim must carry a ChangeSet — no unattributed user writes."""
        with pytest.raises(ValueError, match="requires a changeset"):
            make_claim(mfr, "name", "Williams", user=user)

    def test_source_claim_with_changeset_accepted(self, source, mfr):
        """Source-attributed claims can use ChangeSets linked to matching ingest run."""
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        cs = ChangeSet.objects.create(ingest_run=run)
        claim = make_claim(mfr, "name", "Williams", source=source, changeset=cs)
        assert claim.changeset == cs

    def test_source_claim_changeset_source_mismatch_rejected(self, source, mfr):
        """ChangeSet's ingest run source must match the claim source."""
        other_source = Source.objects.create(
            name="OtherSource", slug="other-source", priority=5
        )
        run = IngestRun.objects.create(
            source=other_source, input_fingerprint="sha256:abc"
        )
        cs = ChangeSet.objects.create(ingest_run=run)
        with pytest.raises(ValueError, match="same source"):
            make_claim(mfr, "name", "Williams", source=source, changeset=cs)

    def test_changeset_user_mismatch_rejected(self, user, mfr):
        """ChangeSet user must match the claim user."""
        other_user = make_user()
        cs = ChangeSet.objects.create(user=other_user, action="edit")
        with pytest.raises(ValueError, match="must match"):
            make_claim(mfr, "name", "Williams", user=user, changeset=cs)

    def test_changeset_survives_claim_superseding(self, user, mfr):
        """When a claim is superseded, the old claim keeps its changeset link."""
        cs1 = ChangeSet.objects.create(user=user, action="edit", note="First edit")
        c1 = make_claim(mfr, "description", "First", user=user, changeset=cs1)

        cs2 = ChangeSet.objects.create(user=user, action="edit", note="Second edit")
        c2 = make_claim(mfr, "description", "Second", user=user, changeset=cs2)

        c1.refresh_from_db()
        assert c1.is_active is False
        assert c1.changeset == cs1
        assert c2.is_active is True
        assert c2.changeset == cs2


@pytest.mark.django_db
class TestChangeSetConstraints:
    def test_user_only(self, user):
        cs = ChangeSet.objects.create(user=user, action="edit")
        assert cs.pk is not None

    def test_ingest_run_only(self, source):
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        cs = ChangeSet.objects.create(ingest_run=run)
        assert cs.pk is not None

    def test_neither_user_nor_ingest_run_rejected(self):
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create()

    def test_both_user_and_ingest_run_rejected(self, user, source):
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(user=user, ingest_run=run)

    def test_user_without_action_rejected(self, user):
        """User ChangeSets must carry an action value."""
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(user=user)

    def test_ingest_run_with_action_rejected(self, source):
        """Ingest ChangeSets must not carry an action value."""
        run = IngestRun.objects.create(source=source, input_fingerprint="sha256:abc")
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(ingest_run=run, action="edit")


@pytest.mark.django_db
class TestClaimConstraints:
    def test_empty_claim_key_rejected(self, source, mfr):
        """DB-level CHECK constraint rejects empty claim_key."""
        from django.db import IntegrityError, connection

        claim = make_claim(mfr, "name", "Williams", source=source)
        with connection.cursor() as cursor, pytest.raises(IntegrityError):
            cursor.execute(
                "UPDATE provenance_claim SET claim_key = '' WHERE id = %s",
                [claim.pk],
            )


@pytest.mark.django_db
class TestClaimProtect:
    def test_delete_user_blocked_by_claims(self, user, mfr):
        """PROTECT prevents deleting a user who has claims."""
        from django.db.models import ProtectedError

        cs = ChangeSet.objects.create(user=user, action="edit")
        make_claim(mfr, "name", "Williams", user=user, changeset=cs)
        with pytest.raises(ProtectedError):
            user.delete()

    def test_delete_changeset_blocked_by_claims(self, user, mfr):
        """PROTECT prevents deleting a ChangeSet that has claims."""
        from django.db.models import ProtectedError

        cs = ChangeSet.objects.create(user=user, action="edit")
        make_claim(mfr, "name", "Williams", user=user, changeset=cs)
        with pytest.raises(ProtectedError):
            cs.delete()

    def test_delete_license_blocked_by_claims(self, source, mfr):
        """PROTECT prevents deleting a License referenced by claims."""
        from django.db.models import ProtectedError

        lic = License.objects.create(name="Test License", short_name="test-lic")
        make_claim(mfr, "name", "Williams", source=source, license=lic)
        with pytest.raises(ProtectedError):
            lic.delete()
