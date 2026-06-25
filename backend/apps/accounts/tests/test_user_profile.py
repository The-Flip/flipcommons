"""Tests for GET /api/pages/user/{username}/ endpoint."""

import pytest
from django.test import Client

from apps.accounts.test_factories import make_user
from apps.catalog.models import Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def manufacturer(db, bootstrap_source):
    mfr = Manufacturer.objects.create(name="Williams", slug="williams")
    make_claim(mfr, "name", "Williams", source=bootstrap_source)
    return mfr


@pytest.fixture
def model_a(db, bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    make_claim(pm, "name", "Medieval Madness", source=bootstrap_source)
    return pm


@pytest.fixture
def model_b(db, bootstrap_source):
    pm = make_machine_model(name="Attack from Mars", slug="attack-from-mars", year=1995)
    make_claim(pm, "name", "Attack from Mars", source=bootstrap_source)
    return pm


@pytest.mark.django_db
class TestUserProfileNotFound:
    def test_nonexistent_user_returns_404(self, client):
        resp = client.get("/api/pages/user/nonexistent/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestUserProfileEmpty:
    def test_user_with_no_edits(self, client, user):
        resp = client.get(f"/api/pages/user/{user.username}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == user.username
        assert data["edit_count"] == 0
        assert data["entities_edited"] == []
        assert data["recent_edits"] == []
        assert "member_since" in data


@pytest.mark.django_db
class TestUserProfileWithEdits:
    def test_single_entity_edit(self, client, user, model_a):
        """Editing one entity shows up in both entities_edited and recent_edits."""
        client.force_login(user)
        client.patch(
            f"/api/models/{model_a.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/user/{user.username}/")
        assert resp.status_code == 200
        data = resp.json()

        assert data["edit_count"] == 1
        assert len(data["entities_edited"]) == 1

        entity = data["entities_edited"][0]
        assert entity["entity"]["href"] == "/models/medieval-madness"
        assert entity["entity"]["name"] == "Medieval Madness"
        assert entity["entity"]["type_label"] == "Model"
        assert entity["edit_count"] == 1

        assert len(data["recent_edits"]) == 1
        edit = data["recent_edits"][0]
        assert edit["entity"]["href"] == "/models/medieval-madness"
        assert edit["entity"]["name"] == "Medieval Madness"

    def test_multiple_entity_edits_ordered_by_recency(
        self, client, user, model_a, model_b
    ):
        """Entities are ordered by most recently edited."""
        client.force_login(user)
        # Edit model_a first
        client.patch(
            f"/api/models/{model_a.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        # Edit model_b second (more recent)
        client.patch(
            f"/api/models/{model_b.slug}/claims/",
            data='{"fields": {"year": 1996}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/user/{user.username}/")
        data = resp.json()

        assert data["edit_count"] == 2
        assert len(data["entities_edited"]) == 2
        # Most recently edited first
        assert data["entities_edited"][0]["entity"]["name"] == "Attack from Mars"
        assert data["entities_edited"][1]["entity"]["name"] == "Medieval Madness"

        # Recent edits also newest first
        assert len(data["recent_edits"]) == 2
        assert data["recent_edits"][0]["entity"]["name"] == "Attack from Mars"
        assert data["recent_edits"][1]["entity"]["name"] == "Medieval Madness"

    def test_multiple_edits_same_entity(self, client, user, model_a):
        """Multiple edits to one entity count correctly."""
        client.force_login(user)
        client.patch(
            f"/api/models/{model_a.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/models/{model_a.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/user/{user.username}/")
        data = resp.json()

        assert data["edit_count"] == 2
        assert len(data["entities_edited"]) == 1
        assert data["entities_edited"][0]["edit_count"] == 2
        assert len(data["recent_edits"]) == 2

    def test_cross_entity_type_edits(self, client, user, model_a, manufacturer):
        """Edits to different entity types are all included."""
        client.force_login(user)
        client.patch(
            f"/api/models/{model_a.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/manufacturers/{manufacturer.slug}/claims/",
            data='{"fields": {"description": "A pinball manufacturer."}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/user/{user.username}/")
        data = resp.json()

        assert data["edit_count"] == 2
        assert len(data["entities_edited"]) == 2
        entity_types = {e["entity"]["type_label"] for e in data["entities_edited"]}
        assert "Model" in entity_types
        assert "Manufacturer" in entity_types

    def test_other_users_edits_not_included(self, client, user, model_a, db):
        """Only the requested user's edits appear."""
        other = make_user()
        client.force_login(other)
        client.patch(
            f"/api/models/{model_a.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/user/{user.username}/")
        data = resp.json()
        assert data["edit_count"] == 0
        assert data["entities_edited"] == []
        assert data["recent_edits"] == []


@pytest.mark.django_db
class TestEditHistoryIngestAttribution:
    """Verify that build_edit_history attributes ingest changesets correctly."""

    def test_ingest_and_user_changesets_attributed_correctly(self, client, user):
        from apps.provenance.test_factories import (
            ingest_changeset,
            ingest_run,
            user_changeset,
        )

        source = Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        pm = make_machine_model(name="Gorgar", slug="gorgar", year=1979)

        ingest_cs = ingest_changeset(ingest_run(source))
        make_claim(pm, "year", 1979, source=source, changeset=ingest_cs)

        user_cs = user_changeset(user)
        make_claim(
            pm,
            "description",
            "First talking pinball machine",
            user=user,
            changeset=user_cs,
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = resp.json()
        attributions = {e["id"]: e["attribution"] for e in data}
        # The model also carries a Bootstrap-source seed name claim from
        # make_machine_model (its own ingest changeset); assert on the two
        # changesets under test rather than the total.
        assert {ingest_cs.pk, user_cs.pk} <= attributions.keys()

        ingest_attr = attributions[ingest_cs.pk]
        assert ingest_attr["author"] == {"kind": "source", "name": "IPDB"}

        user_attr = attributions[user_cs.pk]
        assert user_attr["author"] == {"kind": "user", "username": user.username}
