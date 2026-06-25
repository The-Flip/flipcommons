"""Tests for PATCH /api/manufacturers/{public_id}/claims/ and /api/people/{public_id}/claims/."""

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Manufacturer, Person
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim

User = get_user_model()


@pytest.fixture
def mfr(db, bootstrap_source):
    m = Manufacturer.objects.create(name="Williams", slug="williams")
    make_claim(m, "name", "Williams", source=bootstrap_source)
    return m


@pytest.fixture
def person(db, bootstrap_source):
    p = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
    make_claim(p, "name", "Pat Lawlor", source=bootstrap_source)
    return p


# ---------------------------------------------------------------------------
# Manufacturer claims
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchManufacturerClaimsAuth:
    def test_anonymous_gets_401(self, client, mfr):
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "WMS"}}',
            content_type="application/json",
        )
        assert resp.status_code in (401, 403)

    def test_authenticated_user_can_patch(self, client, user, mfr):
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "WMS"}}',
            content_type="application/json",
        )
        assert resp.status_code == 200


@pytest.mark.django_db
class TestPatchManufacturerClaimsValidation:
    def test_unknown_field_returns_422(self, client, user, mfr):
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"nonexistent_field": "bad"}}',
            content_type="application/json",
        )
        assert resp.status_code == 422

    def test_nonexistent_slug_returns_404(self, client, user):
        client.force_login(user)
        resp = client.patch(
            "/api/manufacturers/does-not-exist/claims/",
            data='{"fields": {"name": "X"}}',
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_duplicate_name_returns_422(self, client, user, mfr):
        Manufacturer.objects.create(name="Bally", slug="bally")
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"name": "Bally"}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()

    def test_invalid_markdown_link_returns_422(self, client, user, mfr):
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "Links to [[system:nope]]."}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "nope" in resp.json()["detail"]["message"].lower()


@pytest.mark.django_db
class TestPatchManufacturerClaimsPersistence:
    def test_claim_created_for_user(self, client, user, mfr):
        client.force_login(user)
        client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "WMS"}}',
            content_type="application/json",
        )
        claim = mfr.claims.get(
            actor=user.actor, field_name="description", is_active=True
        )
        assert claim.value == "WMS"

    def test_model_resolved_and_returned(self, client, user, mfr):
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "WMS"}}',
            content_type="application/json",
        )
        data = resp.json()
        assert data["description"]["text"] == "WMS"
        mfr.refresh_from_db()
        assert mfr.description == "WMS"

    def test_slug_can_be_changed(self, client, user, mfr):
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"slug": "williams-electronics"}}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "williams-electronics"

        mfr.refresh_from_db()
        assert mfr.slug == "williams-electronics"
        assert client.get(f"/api/pages/manufacturer/{mfr.slug}").status_code == 200
        assert client.get("/api/pages/manufacturer/williams").status_code == 404

    def test_duplicate_slug_returns_422(self, client, user, mfr):
        Manufacturer.objects.create(name="Bally", slug="bally")
        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"slug": "bally"}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()

    def test_repeated_edit_supersedes_previous(self, client, user, mfr):
        client.force_login(user)
        client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "First"}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "Second"}}',
            content_type="application/json",
        )
        active = mfr.claims.filter(
            actor=user.actor, field_name="description", is_active=True
        )
        inactive = mfr.claims.filter(
            actor=user.actor, field_name="description", is_active=False
        )
        assert active.count() == 1
        assert inactive.count() == 1
        assert active.first().value == "Second"

    def test_user_claim_beats_lower_priority_source(self, client, user, mfr):
        source = Source.objects.create(
            name="LowPri", source_type="database", priority=10
        )
        make_claim(mfr, "description", "Source Name", source=source)
        from apps.catalog.resolve import resolve_entity

        resolve_entity(mfr)
        mfr.refresh_from_db()
        assert mfr.description == "Source Name"

        client.force_login(user)
        resp = client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"description": "User Name"}}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["description"]["text"] == "User Name"


# ---------------------------------------------------------------------------
# Person claims
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchPersonClaimsAuth:
    def test_anonymous_gets_401(self, client, person):
        resp = client.patch(
            f"/api/people/{person.slug}/claims/",
            data='{"fields": {"description": "A great designer."}}',
            content_type="application/json",
        )
        assert resp.status_code in (401, 403)

    def test_authenticated_user_can_patch(self, client, user, person):
        client.force_login(user)
        resp = client.patch(
            f"/api/people/{person.slug}/claims/",
            data='{"fields": {"description": "A great designer."}}',
            content_type="application/json",
        )
        assert resp.status_code == 200


@pytest.mark.django_db
class TestPatchPersonClaimsValidation:
    pass


@pytest.mark.django_db
class TestPatchPersonClaimsPersistence:
    def test_claim_created_for_user(self, client, user, person):
        client.force_login(user)
        client.patch(
            f"/api/people/{person.slug}/claims/",
            data='{"fields": {"description": "A great designer."}}',
            content_type="application/json",
        )
        claim = person.claims.get(
            actor=user.actor, field_name="description", is_active=True
        )
        assert claim.value == "A great designer."

    def test_model_resolved_and_returned(self, client, user, person):
        client.force_login(user)
        resp = client.patch(
            f"/api/people/{person.slug}/claims/",
            data='{"fields": {"description": "A great designer.", "name": "Pat Lawlor"}}',
            content_type="application/json",
        )
        data = resp.json()
        assert data["description"]["text"] == "A great designer."
        assert data["name"] == "Pat Lawlor"
        person.refresh_from_db()
        assert person.description == "A great designer."

    def test_slug_can_be_changed(self, client, user, person):
        client.force_login(user)
        resp = client.patch(
            f"/api/people/{person.slug}/claims/",
            data='{"fields": {"slug": "pat-lawlor-jr"}}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "pat-lawlor-jr"

        person.refresh_from_db()
        assert person.slug == "pat-lawlor-jr"
        assert client.get(f"/api/pages/person/{person.slug}").status_code == 200
        assert client.get("/api/pages/person/pat-lawlor").status_code == 404

    def test_duplicate_slug_returns_422(self, client, user, person):
        Person.objects.create(name="John Youssi", slug="john-youssi")
        client.force_login(user)
        resp = client.patch(
            f"/api/people/{person.slug}/claims/",
            data='{"fields": {"slug": "john-youssi"}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()
