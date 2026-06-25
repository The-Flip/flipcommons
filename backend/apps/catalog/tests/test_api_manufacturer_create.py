"""Tests for POST /api/manufacturers/.

Manufacturer create is plain ``register_entity_create``;
``include_deleted_name_check`` is auto-enabled because ``Manufacturer.name``
carries a DB-unique constraint, so a soft-deleted name collision surfaces
as a name field error rather than a misleading slug error.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import Manufacturer
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, body: JsonBody):
    return client.post(
        "/api/manufacturers/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _body(**overrides):
    base = {"name": "Stern", "slug": "stern"}
    base.update(overrides)
    return base


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAuth:
    def test_anonymous_rejected(self, client):
        resp = _post(client, _body())
        assert resp.status_code in (401, 403)
        assert not Manufacturer.objects.filter(slug="stern").exists()


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateHappyPath:
    def test_creates_manufacturer_with_claims(self, client, user):
        client.force_login(user)
        resp = _post(client, _body())
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "stern"
        assert body["name"] == "Stern"

        mfr = Manufacturer.objects.get(slug="stern")
        assert mfr.status == "active"

        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        claim_fields = {
            c.field_name: c.value for c in Claim.objects.filter(changeset=cs)
        }
        assert set(claim_fields) == {"name", "slug", "status"}

    def test_note_preserved(self, client, user):
        client.force_login(user)
        resp = _post(client, _body(note="seeding"))
        assert resp.status_code == 201
        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        assert cs.note == "seeding"


# ── Duplicate-name rejection ────────────────────────────────────────


@pytest.mark.django_db
class TestCreateNameCollision:
    def test_exact_name_blocked(self, client, user):
        Manufacturer.objects.create(
            name="Stern", slug="stern-existing", status="active"
        )
        client.force_login(user)
        resp = _post(client, _body(slug="stern-2"))
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_collision_against_deleted_manufacturer(self, client, user):
        """Regression guard: ``Manufacturer.name`` is DB-unique, so a
        soft-deleted row with the same name would otherwise trip the unique
        constraint and surface as a misleading slug collision.
        ``include_deleted_name_check=True`` on the registrar turns it back
        into a field-level name error."""
        Manufacturer.objects.create(
            name="Stern", slug="stern-deleted", status="deleted"
        )
        client.force_login(user)
        resp = _post(client, _body(slug="stern-new"))
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "name" in detail["field_errors"]
        assert "slug" not in detail["field_errors"]


# ── Slug collisions ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateSlugCollision:
    def test_slug_collision_returns_422(self, client, user):
        Manufacturer.objects.create(name="Other", slug="stern", status="active")
        client.force_login(user)
        resp = _post(client, _body(name="Different"))
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Input validation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateInputValidation:
    def test_blank_name_rejected(self, client, user):
        client.force_login(user)
        resp = _post(client, _body(name="   "))
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user):
        client.force_login(user)
        resp = _post(client, _body(slug="Not A Slug"))
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateRateLimit:
    def test_sixth_create_returns_429(self, client, user):
        client.force_login(user)
        for i in range(5):
            resp = _post(client, _body(name=f"Brand {i}", slug=f"brand-{i}"))
            assert resp.status_code == 201, resp.content
        resp = _post(client, _body(name="Brand six", slug="brand-six"))
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_staff_exempt(self, client, staff):
        client.force_login(staff)
        for i in range(10):
            resp = _post(client, _body(name=f"Admin {i}", slug=f"admin-{i}"))
            assert resp.status_code == 201, resp.content
