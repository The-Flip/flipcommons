"""Tests for POST /api/titles/ and the edit-path name-collision check.

Covers the invariants the user-facing Title Create flow is meant to hold:

* name collisions (normalized) reject both at create and at rename;
* slug collisions are surfaced with a distinct, actionable message;
* creates write the expected ChangeSet + claims at user priority;
* rate limiting is per-user, staff-exempt, counts attempts, and the 429
  retry horizon does not drift on repeated blocked calls.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import Title
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, body: JsonBody):
    return client.post(
        "/api/titles/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _patch(client, slug: str, body: JsonBody):
    return client.patch(
        f"/api/titles/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAuth:
    def test_anonymous_rejected(self, client):
        resp = _post(client, {"name": "Godzilla", "slug": "godzilla"})
        assert resp.status_code in (401, 403)
        assert not Title.objects.filter(slug="godzilla").exists()


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateHappyPath:
    def test_creates_title_with_claims(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Godzilla", "slug": "godzilla"})
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "godzilla"
        assert body["name"] == "Godzilla"

        title = Title.objects.get(slug="godzilla")
        assert title.status == "active"

        changesets = ChangeSet.objects.filter(
            actor=user.actor, action=ChangeSetAction.CREATE
        )
        assert changesets.count() == 1
        cs = changesets.first()

        claim_fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert claim_fields == {"name", "slug", "status"}

    def test_note_and_empty_citation(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            {
                "name": "Attack from Mars",
                "slug": "attack-from-mars",
                "note": "Creating during testing",
            },
        )
        assert resp.status_code == 201
        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        assert cs.note == "Creating during testing"


# ── Name collisions ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateNameCollision:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        Title.objects.create(name="Godzilla", slug="godzilla-stern", status="active")

    def test_exact_name_blocked(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Godzilla", "slug": "godzilla-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_normalized_name_blocked(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "The Godzilla!!!", "slug": "godzilla-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_collision_ignores_deleted_titles(self, client, user):
        Title.objects.create(
            name="Scared Stiff", slug="scared-stiff-old", status="deleted"
        )
        client.force_login(user)
        resp = _post(client, {"name": "Scared Stiff", "slug": "scared-stiff-new"})
        assert resp.status_code == 201, resp.content

    def test_collision_catches_null_status_titles(self, client, user):
        """Titles with status=NULL are transitional-active and count for collisions."""
        Title.objects.create(name="Pinbot", slug="pinbot", status=None)
        client.force_login(user)
        resp = _post(client, {"name": "Pinbot", "slug": "pinbot-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]


# ── Slug collisions ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateSlugCollision:
    def test_slug_collision_returns_422(self, client, user):
        Title.objects.create(name="Twilight Zone", slug="twilight-zone")
        client.force_login(user)
        resp = _post(
            client,
            {"name": "Twilight Zone Remake", "slug": "twilight-zone"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "slug" in detail["field_errors"]
        # Error must be the shaped field message, not the raw DB constraint text
        # that execute_claims falls back to.
        assert "Unique constraint violation" not in detail["field_errors"]["slug"]
        assert "Unique constraint violation" not in " ".join(
            detail.get("form_errors", [])
        )

    def test_slug_collision_with_deleted_title(self, client, user):
        """Slug uniqueness is global and applies to deleted rows too."""
        Title.objects.create(name="Old Ghost", slug="old-ghost", status="deleted")
        client.force_login(user)
        resp = _post(client, {"name": "New Old Ghost", "slug": "old-ghost"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Input validation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateInputValidation:
    def test_blank_name_rejected(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "   ", "slug": "nope"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Okay Name", "slug": "Not A Slug"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]

    def test_slug_cannot_have_double_hyphens(self, client, user):
        client.force_login(user)
        resp = _post(client, {"name": "Okay Name", "slug": "a--b"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateRateLimit:
    def test_sixth_create_returns_429(self, client, user):
        client.force_login(user)
        for i in range(5):
            resp = _post(client, {"name": f"Title {i}", "slug": f"title-{i}"})
            assert resp.status_code == 201, resp.content
        resp = _post(client, {"name": "Title six", "slug": "title-six"})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert resp.json()["detail"]["kind"] == "rate_limit"

    def test_failed_validation_still_counts(self, client, user):
        client.force_login(user)
        for _ in range(5):
            # These fail validation but still consume a slot.
            resp = _post(client, {"name": "", "slug": "bad"})
            assert resp.status_code == 422
        resp = _post(client, {"name": "First Real", "slug": "first-real"})
        assert resp.status_code == 429

    def test_429_does_not_drift_retry_horizon(self, client, user):
        """Repeated blocked retries must not push the horizon forward."""
        client.force_login(user)
        for i in range(5):
            resp = _post(client, {"name": f"Title {i}", "slug": f"title-{i}"})
            assert resp.status_code == 201, resp.content
        first = _post(client, {"name": "Block", "slug": "block"})
        assert first.status_code == 429
        first_after = int(first.headers["Retry-After"])

        # Twenty more retries; each should report a retry-after that is
        # not higher than the first (and typically equal or lower as time
        # passes).
        for _ in range(20):
            later = _post(client, {"name": "Block", "slug": "block"})
            assert later.status_code == 429
            assert int(later.headers["Retry-After"]) <= first_after

    def test_staff_exempt(self, client, staff):
        client.force_login(staff)
        for i in range(10):
            resp = _post(client, {"name": f"Admin {i}", "slug": f"admin-{i}"})
            assert resp.status_code == 201, resp.content


# ── Edit-path name collision ────────────────────────────────────────


@pytest.mark.django_db
class TestEditPathNameCollision:
    def test_rename_to_existing_name_blocked(self, client, user):
        Title.objects.create(name="Iron Maiden", slug="iron-maiden")
        existing = Title.objects.create(name="Getaway", slug="getaway")

        client.force_login(user)
        resp = _patch(client, existing.slug, {"fields": {"name": "Iron Maiden"}})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_rename_to_own_name_allowed(self, client, user):
        t = Title.objects.create(name="Fish Tales", slug="fish-tales")
        client.force_login(user)
        # Renaming to the same normalized name (case change) shouldn't trigger
        # a collision error from the collision check.
        resp = _patch(client, t.slug, {"fields": {"name": "Fish Tales"}})
        # May return 422 for "no changes" at the spec level; the important
        # assertion is that it does NOT come back as a name-collision error.
        if resp.status_code == 422:
            assert "name" not in resp.json()["detail"].get("field_errors", {})

    def test_rename_normalized_collision_blocked(self, client, user):
        Title.objects.create(name="Congo", slug="congo")
        t = Title.objects.create(name="Gorilla", slug="gorilla")

        client.force_login(user)
        resp = _patch(client, t.slug, {"fields": {"name": "the CONGO!!!"}})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]
