"""Tests for the ChangeSet model and its integration with Claim."""

import pytest
from django.db import IntegrityError

from apps.accounts.test_factories import make_user
from apps.catalog.models import Manufacturer
from apps.core.models import License
from apps.provenance.changeset_writer import record_changeset
from apps.provenance.models import ChangeSet, ChangeSetAction, Source
from apps.provenance.test_factories import (
    ingest_changeset,
    ingest_run,
    make_claim,
    user_changeset,
)


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
            user=user, actor=user.actor, action="edit", note="Fixed description"
        )
        assert cs.pk is not None
        assert cs.user == user
        assert cs.note == "Fixed description"
        assert cs.created_at is not None

    def test_changeset_without_note(self, user):
        cs = ChangeSet.objects.create(user=user, actor=user.actor, action="edit")
        assert cs.note == ""

    def test_changeset_with_ingest_run(self, source):
        """ChangeSet with ingest_run (no user) is allowed."""
        run = ingest_run(source)
        cs = ChangeSet.objects.create(ingest_run=run, actor=source.actor)
        assert cs.user is None
        assert cs.ingest_run == run


@pytest.mark.django_db
class TestChangeSetClaimGrouping:
    def test_claims_linked_to_changeset(self, user, mfr):
        cs = user_changeset(user, note="Updated fields")
        c1 = make_claim(mfr, "name", "Williams Electronics", user=user, changeset=cs)
        c2 = make_claim(
            mfr, "description", "Pinball manufacturer", user=user, changeset=cs
        )
        assert c1.changeset == cs
        assert c2.changeset == cs
        assert set(cs.claims.values_list("pk", flat=True)) == {c1.pk, c2.pk}

    def test_user_claim_auto_creates_attributed_changeset(self, user, mfr):
        """make_claim with no changeset mints one carrying the user's actor."""
        claim = make_claim(mfr, "name", "Williams", user=user)
        assert claim.changeset is not None
        assert claim.changeset.actor_id == user.actor_id
        assert claim.actor_id == user.actor_id
        assert claim.user == user

    def test_changeset_actor_mismatch_with_user_rejected(self, user, mfr):
        """A changeset whose actor differs from user= fails loudly, rather than
        silently attributing to the changeset's actor."""
        cs = user_changeset(make_user())
        with pytest.raises(ValueError, match="does not match"):
            make_claim(mfr, "name", "Williams", user=user, changeset=cs)

    def test_source_claim_with_changeset_accepted(self, source, mfr):
        """A source claim rides on an ingest ChangeSet's actor."""
        run = ingest_run(source)
        cs = ingest_changeset(run)
        claim = make_claim(mfr, "name", "Williams", source=source, changeset=cs)
        assert claim.changeset == cs
        assert claim.actor_id == source.actor_id
        assert claim.source == source

    def test_changeset_survives_claim_superseding(self, user, mfr):
        """When a claim is superseded, the old claim keeps its changeset link."""
        cs1 = user_changeset(user, note="First edit")
        c1 = make_claim(mfr, "description", "First", user=user, changeset=cs1)

        cs2 = user_changeset(user, note="Second edit")
        c2 = make_claim(mfr, "description", "Second", user=user, changeset=cs2)

        c1.refresh_from_db()
        assert c1.is_active is False
        assert c1.changeset == cs1
        assert c2.is_active is True
        assert c2.changeset == cs2


@pytest.mark.django_db
class TestRecordChangeset:
    """The actor-first funnel's contract (the validations that used to live on
    ``_assert_claim``'s source/user/changeset args)."""

    def test_interactive_requires_action(self, user):
        with pytest.raises(ValueError, match="requires an action"):
            record_changeset(actor=user.actor)

    def test_interactive_requires_user_backed_actor(self, source):
        with pytest.raises(ValueError, match="user-backed actor"):
            record_changeset(actor=source.actor, action=ChangeSetAction.EDIT)

    def test_interactive_sets_user_and_actor(self, user):
        cs = record_changeset(actor=user.actor, action=ChangeSetAction.EDIT)
        assert cs.user == user
        assert cs.actor_id == user.actor_id

    def test_ingest_rejects_action(self, source):
        run = ingest_run(source)
        with pytest.raises(ValueError, match="never carry an action"):
            record_changeset(
                actor=source.actor, ingest_run=run, action=ChangeSetAction.EDIT
            )

    def test_ingest_actor_must_match_run_source(self, source):
        other = Source.objects.create(name="Other", slug="other", priority=5)
        run = ingest_run(source)
        with pytest.raises(ValueError, match="source actor"):
            record_changeset(actor=other.actor, ingest_run=run)

    def test_ingest_sets_run_and_actor(self, source):
        run = ingest_run(source)
        cs = record_changeset(actor=source.actor, ingest_run=run)
        assert cs.ingest_run == run
        assert cs.actor_id == source.actor_id


@pytest.mark.django_db
class TestChangeSetConstraints:
    def test_user_only(self, user):
        cs = ChangeSet.objects.create(user=user, actor=user.actor, action="edit")
        assert cs.pk is not None

    def test_ingest_run_only(self, source):
        run = ingest_run(source)
        cs = ChangeSet.objects.create(ingest_run=run, actor=source.actor)
        assert cs.pk is not None

    def test_neither_user_nor_ingest_run_rejected(self, user):
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(actor=user.actor)

    def test_both_user_and_ingest_run_rejected(self, user, source):
        run = ingest_run(source)
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(user=user, ingest_run=run, actor=user.actor)

    def test_user_without_action_rejected(self, user):
        """User ChangeSets must carry an action value."""
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(user=user, actor=user.actor)

    def test_ingest_run_with_action_rejected(self, source):
        """Ingest ChangeSets must not carry an action value."""
        run = ingest_run(source)
        with pytest.raises(IntegrityError):
            ChangeSet.objects.create(ingest_run=run, actor=source.actor, action="edit")


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

        cs = user_changeset(user)
        make_claim(mfr, "name", "Williams", user=user, changeset=cs)
        with pytest.raises(ProtectedError):
            user.delete()

    def test_delete_changeset_blocked_by_claims(self, user, mfr):
        """PROTECT prevents deleting a ChangeSet that has claims."""
        from django.db.models import ProtectedError

        cs = user_changeset(user)
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
