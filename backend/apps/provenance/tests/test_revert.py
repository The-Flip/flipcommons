"""Tests for per-field claim revert via POST /api/claims/{claim_id}/revert/."""

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.accounts.test_factories import make_user
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import ChangeSetAction, Claim, Source
from apps.provenance.test_factories import make_claim, user_changeset

REVERT_URL = "/api/claims/{claim_id}/revert/"


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )


@pytest.fixture
def pm(db, bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    make_claim(pm, "name", "Medieval Madness", source=bootstrap_source)
    return pm


def _make_user_edit(client, user, pm, fields, note=""):
    """Helper: log in, PATCH claims, return the response."""
    client.force_login(user)
    import json

    return client.patch(
        f"/api/models/{pm.slug}/claims/",
        data=json.dumps({"fields": fields, "note": note}),
        content_type="application/json",
    )


def _get_active_claim(pm, field_name, user):
    ct = ContentType.objects.get_for_model(pm)
    return Claim.objects.get(
        content_type=ct,
        object_id=pm.pk,
        field_name=field_name,
        user=user,
        is_active=True,
    )


def _revert(client, claim_id, note):
    import json

    return client.post(
        REVERT_URL.format(claim_id=claim_id),
        data=json.dumps({"note": note}),
        content_type="application/json",
    )


# ── Core revert behaviour ───────────────────────────────────────


@pytest.mark.django_db
class TestRevertScalar:
    def test_revert_deactivates_claim_and_re_resolves(self, client, user, pm, source):
        """Reverting a user's scalar claim deactivates it; source value surfaces."""
        make_claim(pm, "year", 1998, source=source)
        _make_user_edit(client, user, pm, {"year": 2002})

        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "Wrong year")

        assert resp.status_code == 204
        claim.refresh_from_db()
        assert claim.is_active is False
        assert claim.retracted_by_changeset is not None

        pm.refresh_from_db()
        assert pm.year == 1998  # source value surfaces

    def test_revert_only_user_claim_falls_to_source_or_default(self, client, user, pm):
        """If no source claim exists, field falls to default/null."""
        _make_user_edit(client, user, pm, {"year": 2005})

        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "Removing year")

        assert resp.status_code == 204
        pm.refresh_from_db()
        # year default is None on MachineModel
        assert pm.year is None


@pytest.mark.django_db
class TestRevertPredecessor:
    def test_revert_reactivates_predecessor_claim(self, client, user, pm):
        """Reverting a user's latest edit re-activates their previous edit."""
        _make_user_edit(client, user, pm, {"year": 2001})
        _make_user_edit(client, user, pm, {"year": 2005})

        claim = _get_active_claim(pm, "year", user)
        assert claim.value == 2005

        client.force_login(user)
        resp = _revert(client, claim.pk, "Wrong year")
        assert resp.status_code == 204

        pm.refresh_from_db()
        assert pm.year == 2001

        # The predecessor is now active and revertable.
        predecessor = _get_active_claim(pm, "year", user)
        assert predecessor.value == 2001

    def test_revert_does_not_reactivate_retracted_predecessor(self, client, user, pm):
        """A predecessor that was explicitly retracted should NOT be re-activated."""
        _make_user_edit(client, user, pm, {"year": 2001})
        first_claim = _get_active_claim(pm, "year", user)

        _make_user_edit(client, user, pm, {"year": 2005})
        second_claim = _get_active_claim(pm, "year", user)

        # Manually retract the first claim (simulating an earlier revert).
        cs = user_changeset(user, action=ChangeSetAction.REVERT, note="earlier revert")
        first_claim.retracted_by_changeset = cs
        first_claim.save(update_fields=["retracted_by_changeset"])

        client.force_login(user)
        resp = _revert(client, second_claim.pk, "Undo")
        assert resp.status_code == 204

        pm.refresh_from_db()
        # First claim was retracted so it's not re-activated; field drops to default.
        assert pm.year is None

    def test_revert_chain_walks_back_through_edits(self, client, user, pm):
        """Reverting twice walks back through the edit chain."""
        _make_user_edit(client, user, pm, {"year": 2001})
        _make_user_edit(client, user, pm, {"year": 2003})
        _make_user_edit(client, user, pm, {"year": 2005})

        # Revert 2005 → surfaces 2003
        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        _revert(client, claim.pk, "Undo 2005")
        pm.refresh_from_db()
        assert pm.year == 2003

        # Revert 2003 → surfaces 2001
        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        _revert(client, claim.pk, "Undo 2003")
        pm.refresh_from_db()
        assert pm.year == 2001

        # Revert 2001 → no predecessor, drops to default
        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        _revert(client, claim.pk, "Undo 2001")
        pm.refresh_from_db()
        assert pm.year is None


@pytest.mark.django_db
class TestRevertNonWinning:
    def test_revert_non_winning_claim_deactivates_without_changing_value(
        self, client, user, pm, db
    ):
        """Reverting a lower-priority claim deactivates it; page value unchanged."""
        # User profile default priority is 10000; use a source above that.
        hi_source = Source.objects.create(
            name="HiPri", slug="hipri", source_type="database", priority=20000
        )
        make_claim(pm, "year", 1998, source=hi_source)
        from apps.provenance.resolution import resolve_after_mutation

        resolve_after_mutation(pm, field_names=["year"])
        pm.refresh_from_db()
        assert pm.year == 1998  # source wins

        _make_user_edit(client, user, pm, {"year": 1997})
        pm.refresh_from_db()
        assert pm.year == 1998  # source still wins (higher priority)

        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "Not needed")

        assert resp.status_code == 204
        pm.refresh_from_db()
        assert pm.year == 1998  # unchanged


# ── Authorisation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestRevertAuth:
    def test_self_revert_with_zero_edits_succeeds(self, client, user, pm):
        """A user can always revert their own claims, even with 0 other edits."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "My mistake")
        assert resp.status_code == 204

    def test_revert_others_below_threshold_returns_403(self, client, user, pm, db):
        """Users with <5 edits cannot revert another user's claims."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        other = make_user()
        client.force_login(other)
        resp = _revert(client, claim.pk, "Reverting you")
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["kind"] == "policy_denied"
        assert detail["code"] == "experience_required"
        assert detail["context"] == {"required": 5, "current": 0}
        assert "5 edits" in detail["message"]
        assert "you have 0" in detail["message"]

    def test_revert_others_above_threshold_succeeds(self, client, user, pm, db):
        """Users with 5+ edits can revert another user's claims."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        other = make_user()
        # Create 5 changesets for other user
        for _ in range(5):
            user_changeset(other, note="edit")

        client.force_login(other)
        resp = _revert(client, claim.pk, "Correcting year")
        assert resp.status_code == 204

    def test_unauthenticated_returns_401(self, client, pm):
        resp = _revert(client, 999, "nope")
        assert resp.status_code == 401

    def test_unverified_self_revert_returns_verification_required(
        self, client, user, pm
    ):
        """`claim.revert`'s policy requires email_verified, and the route
        must enforce it — `django_auth` covers auth/active but not
        verification, and `execute_revert` only runs the experience-
        required check (and only for others-revert)."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        unverified = make_user(email_verified=False)
        # We can't create the claim *as* the unverified user via the
        # API — the `catalog.edit` gate would 403 us at PATCH time.
        # Create as the verified `user` fixture, then re-attribute so
        # the revert path exercised is self-revert (which skips the
        # experience-required check and isolates the email gate).
        claim.user = unverified
        claim.save(update_fields=["user"])

        client.force_login(unverified)
        resp = _revert(client, claim.pk, "Reverting my own claim")
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["kind"] == "policy_denied"
        assert detail["code"] == "verification_required"


# ── Validation ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestRevertValidation:
    def test_empty_note_returns_422(self, client, user, pm):
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "")
        assert resp.status_code == 422
        assert "note" in resp.json()["detail"].lower()

    def test_whitespace_only_note_returns_422(self, client, user, pm):
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "   ")
        assert resp.status_code == 422

    def test_source_claim_returns_422(self, client, user, pm, source):
        """Source-attributed claims cannot be reverted."""
        make_claim(pm, "year", 1998, source=source)
        ct = ContentType.objects.get_for_model(pm)
        src_claim = Claim.objects.get(
            content_type=ct,
            object_id=pm.pk,
            field_name="year",
            source=source,
            is_active=True,
        )
        client.force_login(user)
        resp = _revert(client, src_claim.pk, "Trying")
        assert resp.status_code == 422
        assert "source" in resp.json()["detail"].lower()

    def test_inactive_claim_returns_422(self, client, user, pm):
        """Already-inactive claims cannot be reverted."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        # Deactivate manually
        claim.is_active = False
        claim.save(update_fields=["is_active"])

        client.force_login(user)
        resp = _revert(client, claim.pk, "Double revert")
        assert resp.status_code == 422
        assert "inactive" in resp.json()["detail"].lower()

    def test_nonexistent_claim_id_returns_404(self, client, user, pm):
        """A claim id that doesn't exist returns 404."""
        client.force_login(user)
        resp = _revert(client, 999_999_999, "Ghost claim")
        assert resp.status_code == 404

    def test_claim_whose_entity_no_longer_exists_returns_404(self, client, user, pm):
        """A claim whose target entity row has been hard-deleted returns 404,
        not a 500. Entities are normally soft-deleted, but defend against
        the case where admin/cascade has removed the row."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        # Hard-delete the entity (bypassing soft-delete) so the claim's
        # object_id points at nothing.
        from apps.catalog.models import MachineModel

        MachineModel.objects.filter(pk=pm.pk).delete()

        client.force_login(user)
        resp = _revert(client, claim.pk, "Orphaned")
        assert resp.status_code == 404


# ── Multi-user interleaving ──────────────────────────────────────


@pytest.mark.django_db
class TestRevertMultiUser:
    def test_revert_surfaces_next_winner(self, client, user, pm, source, db):
        """A:1998, C:2001, A:2002 → revert A:2002 → surfaces C:2001."""
        make_claim(pm, "year", 1998, source=source)

        user_c = make_user()
        _make_user_edit(client, user_c, pm, {"year": 2001})
        _make_user_edit(client, user, pm, {"year": 2002})

        claim = _get_active_claim(pm, "year", user)
        client.force_login(user)
        resp = _revert(client, claim.pk, "Wrong")

        assert resp.status_code == 204
        pm.refresh_from_db()
        # User profile default priority (10000) beats IPDB source (10),
        # so charlie's claim wins.
        assert pm.year == 2001


# ── Edit history shows retractions ───────────────────────────────


@pytest.mark.django_db
class TestRevertInHistory:
    def test_revert_appears_as_changeset_with_retraction(self, client, user, pm):
        """After reverting, edit history includes the revert changeset with retractions."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        client.force_login(user)
        _revert(client, claim.pk, "Reverting year")

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()

        # Should have 2 changesets: the revert and the original edit
        assert len(data) >= 2

        # The newest changeset should be the revert
        revert_cs = data[0]
        assert revert_cs["note"] == "Reverting year"
        assert len(revert_cs["retractions"]) == 1
        assert revert_cs["retractions"][0]["field_name"] == "year"
        assert revert_cs["retractions"][0]["old_value"]["raw"] == 2005


# ── Claim metadata in edit history ───────────────────────────────


@pytest.mark.django_db
class TestEditHistoryClaimMetadata:
    def test_claim_metadata_populated(self, client, user, pm):
        """Edit history includes claim_id, claim_user_id, is_active, is_winning."""
        _make_user_edit(client, user, pm, {"year": 2005})

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        change = data[0]["changes"][0]

        assert change["claim_id"] is not None
        assert change["claim_user_id"] == user.pk
        assert change["is_active"] is True
        assert change["is_winning"] is True

    def test_reverted_claim_shows_inactive(self, client, user, pm):
        """After revert, the original changeset's claim shows is_active=False."""
        _make_user_edit(client, user, pm, {"year": 2005})
        claim = _get_active_claim(pm, "year", user)

        client.force_login(user)
        _revert(client, claim.pk, "Undo")

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()

        # Find the original edit changeset (the one with a year change, not the revert)
        original = next(
            cs
            for cs in data
            if cs["changes"] and cs["changes"][0]["new_value"]["raw"] == 2005
        )
        change = original["changes"][0]
        assert change["is_active"] is False
        assert change["is_winning"] is False
