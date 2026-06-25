"""Tests for POST /api/people/.

Person create mirrors Title create structurally. The policy difference is
that duplicate names are rejected outright (no disambiguation path), but
the enforcement is the same normalized-name collision check — there just
isn't an expected user workaround.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import Person, PersonAlias
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, body: JsonBody):
    return client.post(
        "/api/people/",
        data=json.dumps(body),
        content_type="application/json",
    )


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAuth:
    def test_anonymous_rejected(self, client):
        resp = _post(client, {"name": "Pat Lawlor", "slug": "pat-lawlor"})
        assert resp.status_code in (401, 403)
        assert not Person.objects.filter(slug="pat-lawlor").exists()


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateHappyPath:
    def test_creates_person_with_claims(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Pat Lawlor", "slug": "pat-lawlor"})
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "pat-lawlor"
        assert body["name"] == "Pat Lawlor"

        person = Person.objects.get(slug="pat-lawlor")
        assert person.status == "active"

        changesets = ChangeSet.objects.filter(
            actor=user.actor, action=ChangeSetAction.CREATE
        )
        assert changesets.count() == 1
        cs = changesets.first()

        claim_fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert claim_fields == {"name", "slug", "status"}

    def test_note_preserved(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            {
                "name": "Steve Ritchie",
                "slug": "steve-ritchie",
                "note": "seeding designer",
            },
        )
        assert resp.status_code == 201
        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        assert cs.note == "seeding designer"


# ── Duplicate-name rejection ────────────────────────────────────────


@pytest.mark.django_db
class TestCreateNameCollision:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        Person.objects.create(
            name="Pat Lawlor", slug="pat-lawlor-existing", status="active"
        )

    def test_exact_name_blocked(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Pat Lawlor", "slug": "pat-lawlor-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_normalized_name_blocked(self, client, user):
        """Case / punctuation shouldn't allow a backdoor duplicate."""
        client.force_login(user)
        resp = _post(client, {"name": "pat lawlor!!!", "slug": "pat-lawlor-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_collision_ignores_deleted_people(self, client, user):
        Person.objects.create(name="Old Name", slug="old-name", status="deleted")
        client.force_login(user)
        resp = _post(client, {"name": "Old Name", "slug": "old-name-new"})
        assert resp.status_code == 201, resp.content


# ── Slug collisions ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateSlugCollision:
    def test_slug_collision_returns_422(self, client, user):
        Person.objects.create(name="Someone Else", slug="taken-slug")
        client.force_login(user)
        resp = _post(client, {"name": "Distinct Name", "slug": "taken-slug"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "slug" in detail["field_errors"]


# ── Input validation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateInputValidation:
    def test_blank_name_rejected(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "   ", "slug": "someone"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Someone", "slug": "Not A Slug"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]

    def test_alias_collision_rejected(self, client, user):
        existing = Person.objects.create(
            name="Robert Smith", slug="robert-smith", status="active"
        )
        PersonAlias.objects.create(person=existing, value="Bob Smith")

        client.force_login(user)
        resp = _post(client, {"name": "Bob Smith", "slug": "bob-smith"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]
        assert not Person.objects.filter(slug="bob-smith").exists()


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateRateLimit:
    def test_sixth_create_returns_429(self, client, user):
        client.force_login(user)
        for i in range(5):
            resp = _post(client, {"name": f"Person {i}", "slug": f"person-{i}"})
            assert resp.status_code == 201, resp.content
        resp = _post(client, {"name": "Person six", "slug": "person-six"})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_staff_exempt(self, client, staff):
        client.force_login(staff)
        for i in range(10):
            resp = _post(client, {"name": f"Admin {i}", "slug": f"admin-{i}"})
            assert resp.status_code == 201, resp.content
