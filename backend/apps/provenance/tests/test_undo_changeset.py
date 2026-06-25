"""Unit tests for ``execute_undo_changeset`` — atomic inverse of a DELETE.

The delete endpoint's Undo toast relies on this primitive. These tests
pin the eligibility rules (scope to DELETE, author-only, latest-action)
and the atomic rollback so that regressions don't silently turn the
toast into a broken button.
"""

from __future__ import annotations

import pytest

from apps.accounts.test_factories import make_user
from apps.catalog.engine.entity_api.delete import execute_soft_delete
from apps.catalog.models import Title
from apps.provenance.models import ChangeSet, ChangeSetAction, Source
from apps.provenance.revert import UndoError, execute_undo_changeset
from apps.provenance.test_factories import make_claim, user_changeset

pytestmark = pytest.mark.django_db


def _require_changeset(changeset: ChangeSet | None) -> ChangeSet:
    assert changeset is not None
    return changeset


@pytest.fixture
def author(db):
    return make_user()


def _title(slug: str, source: Source) -> Title:
    label = slug.replace("-", " ").title()
    t = Title.objects.create(name=label, slug=slug, status="active")
    # Seed name + status claims so the resolver has something to fall
    # back to after an undo deactivates the user's claim.
    make_claim(t, "name", label, source=source)
    make_claim(t, "status", "active", source=source)
    return t


class TestEligibility:
    def test_rejects_non_delete_changeset(self, author):
        cs = user_changeset(author, action=ChangeSetAction.EDIT)
        with pytest.raises(UndoError):
            execute_undo_changeset(cs, user=author)

    def test_rejects_when_claims_already_superseded(self, author, bootstrap_source):
        t = _title("g", bootstrap_source)
        cs, _ = execute_soft_delete(t, user=author)
        # Supersede the status=deleted claim with a status=active claim.

        make_claim(t, "status", "active", user=author, changeset=user_changeset(author))
        with pytest.raises(UndoError):
            execute_undo_changeset(_require_changeset(cs), user=author)


class TestInverseBehavior:
    def test_reverts_cascaded_delete_atomically(self, author, bootstrap_source):
        from apps.catalog.models import MachineModel

        t = _title("mm", bootstrap_source)
        m = MachineModel.objects.create(
            title=t, name="MM Pro", slug="mm-pro", status="active"
        )
        make_claim(m, "name", "MM Pro", source=bootstrap_source)
        make_claim(m, "status", "active", source=bootstrap_source)
        delete_cs, _ = execute_soft_delete(t, user=author)

        t.refresh_from_db()
        m.refresh_from_db()
        assert t.status == "deleted"
        assert m.status == "deleted"

        revert_cs = execute_undo_changeset(
            _require_changeset(delete_cs), user=author, note="oops"
        )
        assert revert_cs.action == ChangeSetAction.REVERT
        assert revert_cs.note == "oops"

        t.refresh_from_db()
        m.refresh_from_db()
        assert t.status == "active"
        assert m.status == "active"

        # All delete-side claims are deactivated and point at the revert
        # changeset as their retractor.
        for claim in _require_changeset(delete_cs).claims.all():
            assert claim.is_active is False
            assert claim.retracted_by_changeset_id == revert_cs.pk

    def test_reactivates_prior_user_claim_if_any(self, author, bootstrap_source):
        t = _title("g", bootstrap_source)
        # User first asserts status=active (their own prior claim).
        prior = make_claim(
            t, "status", "active", user=author, changeset=user_changeset(author)
        )
        # Then deletes.
        delete_cs, _ = execute_soft_delete(t, user=author)
        prior.refresh_from_db()
        assert prior.is_active is False

        execute_undo_changeset(_require_changeset(delete_cs), user=author)
        prior.refresh_from_db()
        assert prior.is_active is True


class TestChangeSetNotFound:
    def test_missing_claims_noop_rejected(self, author):
        cs = user_changeset(author, action=ChangeSetAction.DELETE)
        with pytest.raises(UndoError):
            execute_undo_changeset(cs, user=author)
