"""Tests for GET /api/pages/edit-history/{entity_type}/{public_id}/ endpoint."""

import pytest

from apps.accounts.test_factories import make_user
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim


@pytest.fixture
def _bootstrap_source(db):
    """Low-priority source for seeding name claims."""
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


@pytest.fixture
def source(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def pm(db, _bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    make_claim(pm, "name", "Medieval Madness", source=_bootstrap_source)
    return pm


@pytest.mark.django_db
class TestEditHistoryEmpty:
    def test_no_changesets_returns_empty_list(self, client, pm):
        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_nonexistent_slug_returns_404(self, client):
        resp = client.get("/api/pages/edit-history/model/does-not-exist/")
        assert resp.status_code == 404

    def test_source_claims_not_included(self, client, pm, source):
        """Source-attributed claims (no changeset) should not appear."""
        make_claim(pm, "year", 1998, source=source)
        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.django_db
class TestEditHistoryBasic:
    def test_single_changeset_returned(self, client, user, pm):
        """A single edit session shows up with field changes."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        cs = data[0]
        assert cs["attribution"]["author"] == {
            "kind": "user",
            "username": user.username,
        }
        assert cs["note"] == ""
        assert len(cs["changes"]) == 1
        assert cs["changes"][0]["field_name"] == "year"
        assert cs["changes"][0]["new_value"]["raw"] == 1998
        # First edit — no old value
        assert cs["changes"][0]["old_value"] is None

    def test_old_value_shown_on_second_edit(self, client, user, pm):
        """When a field is edited twice, the second changeset shows old→new."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        assert len(data) == 2

        # Most recent first
        newest = data[0]
        assert newest["changes"][0]["field_name"] == "year"
        assert newest["changes"][0]["old_value"]["raw"] == 1998
        assert newest["changes"][0]["new_value"]["raw"] == 1999

        oldest = data[1]
        assert oldest["changes"][0]["old_value"] is None
        assert oldest["changes"][0]["new_value"]["raw"] == 1998


@pytest.mark.django_db
class TestEditHistoryMultipleFields:
    def test_multi_field_changeset(self, client, user, pm):
        """A single edit that changes multiple fields shows all changes."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998, "player_count": 4}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        assert len(data) == 1

        field_names = {c["field_name"] for c in data[0]["changes"]}
        assert field_names == {"year", "player_count"}


@pytest.mark.django_db
class TestEditHistoryMultiUser:
    def test_old_value_uses_any_prior_claim(self, client, user, pm, db):
        """User B editing after User A should see User A's value as the old value."""
        user_b = make_user()

        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.force_login(user_b)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        assert len(data) == 2

        # User B's edit is newest — old value is User A's prior claim
        assert data[0]["attribution"]["author"] == {
            "kind": "user",
            "username": user_b.username,
        }
        assert data[0]["changes"][0]["old_value"]["raw"] == 1998
        assert data[0]["changes"][0]["new_value"]["raw"] == 1999

        # User A's edit — no prior claim, so no old value
        assert data[1]["attribution"]["author"] == {
            "kind": "user",
            "username": user.username,
        }
        assert data[1]["changes"][0]["old_value"] is None
        assert data[1]["changes"][0]["new_value"]["raw"] == 1998

    def test_old_value_uses_source_claim(self, client, user, pm, source):
        """A user edit shows the prior source/ingest claim's value as old."""
        make_claim(pm, "year", 1997, source=source)

        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["changes"][0]["old_value"]["raw"] == 1997
        assert data[0]["changes"][0]["new_value"]["raw"] == 1999


@pytest.mark.django_db
class TestEditHistoryOrdering:
    def test_newest_first(self, client, user, pm):
        """Changesets are returned newest first."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"player_count": 4}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        assert len(data) == 2
        # Newest changeset (player_count) first
        assert data[0]["changes"][0]["field_name"] == "player_count"
        assert data[1]["changes"][0]["field_name"] == "year"


@pytest.mark.django_db
class TestEditHistorySoftDeleted:
    def test_soft_deleted_entity_still_returns_history(self, client, user, pm):
        """Soft-delete is soft: audit trail remains inspectable by public_id.

        Policy: provenance surfaces intentionally use the default manager
        (not ``.active()``) so deleted entities keep their history visible
        to direct API callers. See ``edit_history_page`` docstring.
        """
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        pm.status = "deleted"
        pm.save(update_fields=["status"])

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["changes"][0]["new_value"]["raw"] == 1998


@pytest.mark.django_db
class TestEditHistoryEntityTypeGuard:
    def test_unknown_entity_type_returns_404(self, client):
        resp = client.get("/api/pages/edit-history/nonexistent/some-slug/")
        assert resp.status_code == 404

    def test_non_linkable_entity_type_returns_404(self, client):
        """Models that aren't LinkableModel subclasses (e.g. Location) should be rejected."""
        resp = client.get("/api/pages/edit-history/location/some-slug/")
        assert resp.status_code == 404
