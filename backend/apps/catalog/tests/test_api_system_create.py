"""Tests for POST /api/systems/.

System create mirrors Person create but adds a required ``manufacturer_slug``
FK and flexes the ``include_deleted=True`` collision path because
``System.name`` is DB-unique.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import Manufacturer, System
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim


@pytest.fixture
def mfr(db):
    return Manufacturer.objects.create(name="Stern", slug="stern", status="active")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, body: JsonBody):
    return client.post(
        "/api/systems/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _body(mfr, **overrides):
    base = {"name": "SPIKE", "slug": "spike", "manufacturer_slug": mfr.slug}
    base.update(overrides)
    return base


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAuth:
    def test_anonymous_rejected(self, client, mfr):
        resp = _post(client, _body(mfr))
        assert resp.status_code in (401, 403)
        assert not System.objects.filter(slug="spike").exists()


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateHappyPath:
    def test_creates_system_with_claims(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, _body(mfr))
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "spike"
        assert body["name"] == "SPIKE"
        assert body["manufacturer"]["public_id"] == "stern"

        system = System.objects.get(slug="spike")
        assert system.status == "active"
        assert system.manufacturer == mfr

        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        claim_fields = {
            c.field_name: c.value for c in Claim.objects.filter(changeset=cs)
        }
        assert set(claim_fields) == {"name", "slug", "status", "manufacturer"}
        # FK claim value is the parent's slug string.
        assert claim_fields["manufacturer"] == "stern"

    def test_note_preserved(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, _body(mfr, note="seeding system"))
        assert resp.status_code == 201
        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        assert cs.note == "seeding system"


# ── Manufacturer resolution ─────────────────────────────────────────


@pytest.mark.django_db
class TestManufacturerResolution:
    def test_missing_manufacturer_slug_rejected(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, _body(mfr, manufacturer_slug=""))
        assert resp.status_code == 422
        assert "manufacturer_slug" in resp.json()["detail"]["field_errors"]

    def test_unknown_manufacturer_rejected(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            {
                "name": "SPIKE",
                "slug": "spike",
                "manufacturer_slug": "does-not-exist",
            },
        )
        assert resp.status_code == 422
        assert "manufacturer_slug" in resp.json()["detail"]["field_errors"]

    def test_deleted_manufacturer_rejected(self, client, user, mfr):
        mfr.status = "deleted"
        mfr.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(client, _body(mfr))
        assert resp.status_code == 422
        assert "manufacturer_slug" in resp.json()["detail"]["field_errors"]


# ── Duplicate-name rejection ────────────────────────────────────────


@pytest.mark.django_db
class TestCreateNameCollision:
    def test_exact_name_blocked(self, client, user, mfr):
        System.objects.create(
            name="SPIKE", slug="spike-existing", manufacturer=mfr, status="active"
        )
        client.force_login(user)
        resp = _post(client, _body(mfr, slug="spike-2"))
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_collision_against_deleted_system(self, client, user, mfr):
        """Regression guard: System.name is DB-unique, so a soft-deleted row
        with the same name would otherwise trip the unique constraint and
        surface as a misleading slug collision. ``include_deleted=True`` on
        ``assert_name_available`` turns it back into a name field error."""
        System.objects.create(
            name="SPIKE", slug="spike-deleted", manufacturer=mfr, status="deleted"
        )
        client.force_login(user)
        resp = _post(client, _body(mfr, slug="spike-new"))
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "name" in detail["field_errors"]
        assert "slug" not in detail["field_errors"]


# ── Slug collisions ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateSlugCollision:
    def test_slug_collision_returns_422(self, client, user, mfr):
        System.objects.create(
            name="Other", slug="spike", manufacturer=mfr, status="active"
        )
        client.force_login(user)
        resp = _post(client, _body(mfr, name="Different"))
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Input validation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateInputValidation:
    def test_blank_name_rejected(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, _body(mfr, name="   "))
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, _body(mfr, slug="Not A Slug"))
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateRateLimit:
    def test_sixth_create_returns_429(self, client, user, mfr):
        client.force_login(user)
        for i in range(5):
            resp = _post(client, _body(mfr, name=f"System {i}", slug=f"system-{i}"))
            assert resp.status_code == 201, resp.content
        resp = _post(client, _body(mfr, name="System six", slug="system-six"))
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_staff_exempt(self, client, staff, mfr):
        client.force_login(staff)
        for i in range(10):
            resp = _post(client, _body(mfr, name=f"Admin {i}", slug=f"admin-{i}"))
            assert resp.status_code == 201, resp.content
