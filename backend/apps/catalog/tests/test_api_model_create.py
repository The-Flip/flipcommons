"""Tests for POST /api/titles/{title_public_id}/models/.

Model Create mirrors Title Create on the shared ``entity_create`` helpers.
These tests cover the invariants unique to Model Create — parent Title
resolution, title-scoped name collision, and that the create rate-limit
bucket is shared with Title Create — plus the usual create-pattern checks
(auth, happy path, slug uniqueness, input validation, rate limits).
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import MachineModel, Title
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim


@pytest.fixture
def godzilla(db):
    return Title.objects.create(name="Godzilla", slug="godzilla", status="active")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, title_slug: str, body: JsonBody):
    return client.post(
        f"/api/titles/{title_slug}/models/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _post_title(client, body: JsonBody):
    return client.post(
        "/api/titles/",
        data=json.dumps(body),
        content_type="application/json",
    )


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateAuth:
    def test_anonymous_rejected(self, client, godzilla):
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "godzilla-pro"})
        assert resp.status_code in (401, 403)
        assert not MachineModel.objects.filter(slug="godzilla-pro").exists()


# ── Parent title resolution ─────────────────────────────────────────


@pytest.mark.django_db
class TestParentTitle:
    def test_missing_title_returns_404(self, client, user):
        client.force_login(user)
        resp = _post(
            client, "no-such-title", {"name": "Pro", "slug": "no-such-title-pro"}
        )
        assert resp.status_code == 404

    def test_soft_deleted_title_returns_404(self, client, user):
        Title.objects.create(name="Ghost", slug="ghost", status="deleted")
        client.force_login(user)
        resp = _post(client, "ghost", {"name": "Pro", "slug": "ghost-pro"})
        assert resp.status_code == 404


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateHappyPath:
    def test_creates_model_with_claims(self, client, user, godzilla):
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "godzilla-pro"})
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "godzilla-pro"
        assert body["name"] == "Pro"

        mm = MachineModel.objects.get(slug="godzilla-pro")
        assert mm.status == "active"
        assert mm.title_id == godzilla.pk

        changesets = ChangeSet.objects.filter(
            actor=user.actor, action=ChangeSetAction.CREATE
        )
        assert changesets.count() == 1
        cs = changesets.first()

        claim_fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        # Note: status claim for Model is written under field_name "status"
        # just like Title. The title FK claim is also written.
        assert claim_fields == {"name", "slug", "status", "title"}

        # The title claim carries the parent's PK, matching ingest's
        # convention for FK claims on MachineModel.
        title_claim = Claim.objects.get(changeset=cs, field_name="title")
        assert title_claim.value == godzilla.pk

    def test_note_and_empty_citation(self, client, user, godzilla):
        client.force_login(user)
        resp = _post(
            client,
            godzilla.slug,
            {
                "name": "Premium",
                "slug": "godzilla-premium",
                "note": "Adding the premium variant",
            },
        )
        assert resp.status_code == 201
        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        assert cs.note == "Adding the premium variant"


# ── Name collisions (title-scoped) ──────────────────────────────────


@pytest.mark.django_db
class TestCreateNameCollision:
    def test_same_name_in_same_title_blocked(self, client, user, godzilla):
        MachineModel.objects.create(
            name="Pro", slug="godzilla-pro", title=godzilla, status="active"
        )
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "godzilla-pro-2"})
        assert resp.status_code == 422
        body = resp.json()
        assert "name" in body["detail"]["field_errors"]
        assert "model" in body["detail"]["field_errors"]["name"].lower()

    def test_same_name_in_different_title_allowed(self, client, user, godzilla):
        """Two titles can legitimately share a model name (e.g. "Pro")."""
        other_title = Title.objects.create(
            name="Attack from Mars", slug="attack-from-mars", status="active"
        )
        MachineModel.objects.create(
            name="Pro", slug="afm-pro", title=other_title, status="active"
        )
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "godzilla-pro"})
        assert resp.status_code == 201, resp.content

    def test_normalized_name_blocked(self, client, user, godzilla):
        MachineModel.objects.create(
            name="Pro", slug="godzilla-pro", title=godzilla, status="active"
        )
        client.force_login(user)
        resp = _post(
            client, godzilla.slug, {"name": "THE Pro!!!", "slug": "godzilla-pro-2"}
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_collision_ignores_deleted_models(self, client, user, godzilla):
        MachineModel.objects.create(
            name="Pro", slug="godzilla-pro-old", title=godzilla, status="deleted"
        )
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "godzilla-pro"})
        assert resp.status_code == 201, resp.content


# ── Slug collisions (global) ────────────────────────────────────────


@pytest.mark.django_db
class TestCreateSlugCollision:
    def test_slug_collision_across_titles_blocked(self, client, user, godzilla):
        """Model slug uniqueness is global, not title-scoped."""
        other_title = Title.objects.create(
            name="Attack from Mars", slug="attack-from-mars", status="active"
        )
        MachineModel.objects.create(
            name="Pro", slug="shared-slug", title=other_title, status="active"
        )
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "shared-slug"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "slug" in detail["field_errors"]
        # Must be the shaped field message, not the raw DB-constraint fallback.
        assert "Unique constraint violation" not in detail["field_errors"]["slug"]
        assert "Unique constraint violation" not in " ".join(
            detail.get("form_errors", [])
        )

    def test_slug_collision_with_deleted_model(self, client, user, godzilla):
        """Slug uniqueness is global and applies to deleted rows too."""
        other_title = Title.objects.create(
            name="Ghost Title", slug="ghost-title", status="active"
        )
        MachineModel.objects.create(
            name="Old", slug="old-slug", title=other_title, status="deleted"
        )
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Pro", "slug": "old-slug"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Input validation ────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateInputValidation:
    def test_blank_name_rejected(self, client, user, godzilla):
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "   ", "slug": "nope"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_invalid_slug_rejected(self, client, user, godzilla):
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Okay", "slug": "Not A Slug"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]

    def test_slug_cannot_have_double_hyphens(self, client, user, godzilla):
        client.force_login(user)
        resp = _post(client, godzilla.slug, {"name": "Okay", "slug": "a--b"})
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]


# ── Rate limiting (shared create bucket) ────────────────────────────


@pytest.mark.django_db
class TestCreateRateLimit:
    def test_sixth_create_returns_429(self, client, user, godzilla):
        client.force_login(user)
        for i in range(5):
            resp = _post(
                client,
                godzilla.slug,
                {"name": f"M{i}", "slug": f"godzilla-m-{i}"},
            )
            assert resp.status_code == 201, resp.content
        resp = _post(client, godzilla.slug, {"name": "Six", "slug": "godzilla-six"})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_shared_bucket_with_title_create(self, client, user, godzilla):
        """Title Create and Model Create share the same create bucket.

        One burst of Title + Model creates together must cap at the bucket
        limit, not per record type. The product doc is explicit: "Restore
        uses the same bucket as create" — implying one bucket, many
        record-create types.
        """
        client.force_login(user)
        # 3 Title creates + 2 Model creates should be fine (5 total).
        for i in range(3):
            resp = _post_title(client, {"name": f"T{i}", "slug": f"t{i}"})
            assert resp.status_code == 201, resp.content
        for i in range(2):
            resp = _post(
                client,
                godzilla.slug,
                {"name": f"M{i}", "slug": f"godzilla-m-{i}"},
            )
            assert resp.status_code == 201, resp.content
        # 6th overall create: should be blocked regardless of type.
        resp = _post(client, godzilla.slug, {"name": "Six", "slug": "godzilla-six"})
        assert resp.status_code == 429

    def test_failed_validation_still_counts(self, client, user, godzilla):
        client.force_login(user)
        for _ in range(5):
            resp = _post(client, godzilla.slug, {"name": "", "slug": "bad"})
            assert resp.status_code == 422
        resp = _post(client, godzilla.slug, {"name": "Real", "slug": "godzilla-real"})
        assert resp.status_code == 429

    def test_staff_exempt(self, client, staff, godzilla):
        client.force_login(staff)
        for i in range(10):
            resp = _post(
                client,
                godzilla.slug,
                {"name": f"Admin{i}", "slug": f"godzilla-admin-{i}"},
            )
            assert resp.status_code == 201, resp.content
