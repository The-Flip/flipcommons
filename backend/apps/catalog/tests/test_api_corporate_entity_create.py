"""Tests for POST /api/manufacturers/{parent_public_id}/corporate-entities/.

CE create is parented under Manufacturer and uses the shared
``register_entity_create`` with a ``scope_filter_builder`` — sibling CEs
under the *same* manufacturer can't share a name, but the same name can
exist under different manufacturers.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.catalog.models import CorporateEntity, Manufacturer
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim

User = get_user_model()


@pytest.fixture
def mfr(db):
    return Manufacturer.objects.create(name="Stern", slug="stern", status="active")


@pytest.fixture
def other_mfr(db):
    return Manufacturer.objects.create(
        name="Gottlieb", slug="gottlieb", status="active"
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, parent_slug: str, body: JsonBody):
    return client.post(
        f"/api/manufacturers/{parent_slug}/corporate-entities/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _body(**overrides):
    base = {"name": "Stern Pinball Inc.", "slug": "stern-pinball-inc"}
    base.update(overrides)
    return base


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAuth:
    def test_anonymous_rejected(self, client, mfr):
        resp = _post(client, "stern", _body())
        assert resp.status_code in (401, 403)
        assert not CorporateEntity.objects.filter(slug="stern-pinball-inc").exists()


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateHappyPath:
    def test_creates_ce_with_manufacturer_claim(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, "stern", _body())
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "stern-pinball-inc"
        assert body["manufacturer"]["public_id"] == "stern"

        ce = CorporateEntity.objects.get(slug="stern-pinball-inc")
        assert ce.manufacturer == mfr
        assert ce.status == "active"

        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        claim_fields = {
            c.field_name: c.value for c in Claim.objects.filter(changeset=cs)
        }
        assert set(claim_fields) == {"name", "slug", "status", "manufacturer"}
        # FK claim value is the parent's PK.
        assert claim_fields["manufacturer"] == mfr.pk


# ── Parent resolution ───────────────────────────────────────────────


@pytest.mark.django_db
class TestParentResolution:
    def test_unknown_parent_404s(self, client, user):
        client.force_login(user)
        resp = _post(client, "does-not-exist", _body())
        assert resp.status_code == 404

    def test_soft_deleted_parent_404s(self, client, user, mfr):
        mfr.status = "deleted"
        mfr.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(client, "stern", _body())
        assert resp.status_code == 404


# ── Scoped name collision ───────────────────────────────────────────


@pytest.mark.django_db
class TestCreateScopedNameCollision:
    def test_same_name_same_parent_blocked(self, client, user, mfr):
        CorporateEntity.objects.create(
            name="Stern Pinball Inc.",
            slug="stern-pinball-existing",
            manufacturer=mfr,
            status="active",
        )
        client.force_login(user)
        resp = _post(client, "stern", _body(slug="stern-pinball-v2"))
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_same_name_different_parent_allowed(self, client, user, mfr, other_mfr):
        """Regression guard on ``scope_filter_builder``: two manufacturers
        may each own a CE with the same (normalized) name."""
        CorporateEntity.objects.create(
            name="Productions",
            slug="stern-productions",
            manufacturer=mfr,
            status="active",
        )
        client.force_login(user)
        resp = _post(
            client,
            "gottlieb",
            {"name": "Productions", "slug": "gottlieb-productions"},
        )
        assert resp.status_code == 201, resp.content


# ── Slug collision (global) ─────────────────────────────────────────


@pytest.mark.django_db
class TestCreateSlugCollision:
    def test_slug_collision_is_global(self, client, user, mfr, other_mfr):
        """``CorporateEntity.slug`` is globally unique; slug collision
        must trip even if the colliding row is under a different parent."""
        CorporateEntity.objects.create(
            name="Foo",
            slug="shared-slug",
            manufacturer=other_mfr,
            status="active",
        )
        client.force_login(user)
        resp = _post(client, "stern", _body(slug="shared-slug"))
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Input validation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateInputValidation:
    def test_blank_name_rejected(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, "stern", _body(name="  "))
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user, mfr):
        client.force_login(user)
        resp = _post(client, "stern", _body(slug="Not A Slug"))
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]
