"""End-to-end tests for CorporateEntity delete/preview/restore.

CE delete is plain ``register_entity_delete_restore``. The relevant PROTECT
blocker is ``MachineModel.corporate_entity`` (nullable, PROTECT).
``CorporateEntityLocation`` is an owned child row and rides with CE
visibility — not a delete blocker.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    MachineModel,
    Manufacturer,
    Title,
)
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim, Source

User = get_user_model()


@pytest.fixture
def bootstrap_source(db):
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


@pytest.fixture
def mfr(db, bootstrap_source):
    m = Manufacturer.objects.create(name="Stern", slug="stern", status="active")
    Claim.objects.assert_claim(m, "name", "Stern", source=bootstrap_source)
    return m


@pytest.fixture
def ce(db, bootstrap_source, mfr):
    c = CorporateEntity.objects.create(
        name="Stern Pinball Inc.",
        slug="stern-pinball-inc",
        manufacturer=mfr,
        status="active",
    )
    Claim.objects.assert_claim(c, "name", c.name, source=bootstrap_source)
    Claim.objects.assert_claim(c, "status", "active", source=bootstrap_source)
    return c


def _make_model(
    bootstrap_source, ce, slug: str, *, status: str = "active"
) -> MachineModel:
    title = Title.objects.create(
        name=slug.replace("-", " ").title(),
        slug=f"{slug}-title",
        status="active",
    )
    Claim.objects.assert_claim(title, "name", title.name, source=bootstrap_source)
    m = MachineModel.objects.create(
        title=title,
        name=slug.replace("-", " ").title(),
        slug=slug,
        corporate_entity=ce,
        status=status,
    )
    Claim.objects.assert_claim(m, "name", m.name, source=bootstrap_source)
    return m


def _post_delete(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/corporate-entities/{slug}/delete/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _post_restore(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/corporate-entities/{slug}/restore/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _get_preview(client, slug: str):
    return client.get(f"/api/corporate-entities/{slug}/delete-preview/")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAuth:
    def test_anonymous_rejected(self, client, ce):
        resp = _post_delete(client, ce.slug)
        assert resp.status_code in (401, 403)
        ce.refresh_from_db()
        assert ce.status == "active"


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteHappyPath:
    def test_deletes_bare_ce(self, client, user, ce):
        client.force_login(user)
        resp = _post_delete(client, ce.slug, {"note": "bye"})
        assert resp.status_code == 200, resp.content

        ce.refresh_from_db()
        assert ce.status == "deleted"

        cs = ChangeSet.objects.get(pk=resp.json()["changeset_id"])
        assert cs.action == ChangeSetAction.DELETE
        assert cs.note == "bye"


# ── PROTECT blocker: active MachineModel ────────────────────────────


@pytest.mark.django_db
class TestDeletePROTECTBlocker:
    def test_active_model_blocks(self, client, user, bootstrap_source, ce):
        _make_model(bootstrap_source, ce, "mm-pro")
        client.force_login(user)
        resp = _post_delete(client, ce.slug)
        assert resp.status_code == 422
        assert resp.json()["blocked_by"]
        ce.refresh_from_db()
        assert ce.status == "active"

    def test_deleted_models_do_not_block(self, client, user, bootstrap_source, ce):
        _make_model(bootstrap_source, ce, "mm-zombie", status="deleted")
        client.force_login(user)
        resp = _post_delete(client, ce.slug)
        assert resp.status_code == 200, resp.content
        ce.refresh_from_db()
        assert ce.status == "deleted"


# ── Owned-child rows: CorporateEntityLocation does not block ────────


@pytest.mark.django_db
class TestDeleteOwnedChildren:
    def test_ce_location_does_not_block(self, client, user, ce):
        """CorporateEntityLocation rows are owned children (see
        backend/apps/catalog/models/location.py). They ride with CE
        visibility and must not surface as delete blockers."""
        loc = Location.objects.create(name="USA", slug="usa", location_path="usa")
        CorporateEntityLocation.objects.create(corporate_entity=ce, location=loc)
        client.force_login(user)
        resp = _post_delete(client, ce.slug)
        # Location.on_delete=PROTECT but the row itself owned-by CE; the
        # through table has no on_delete=PROTECT back to CE, so this must
        # pass through without surfacing as a blocker.
        assert resp.status_code == 200, resp.content


# ── Already deleted ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteIdempotence:
    def test_already_deleted_returns_404(self, client, user, ce):
        ce.status = "deleted"
        ce.save(update_fields=["status"])
        client.force_login(user)
        resp = _post_delete(client, ce.slug)
        assert resp.status_code == 404


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRestore:
    def test_restores_status_active(self, client, user, ce):
        client.force_login(user)
        _post_delete(client, ce.slug)
        ce.refresh_from_db()
        assert ce.status == "deleted"

        resp = _post_restore(client, ce.slug)
        assert resp.status_code == 200, resp.content
        ce.refresh_from_db()
        assert ce.status == "active"

    def test_restore_requires_active_parent(self, client, user, ce, mfr):
        """If the parent manufacturer is soft-deleted, restoring a CE
        should be blocked — the registrar enforces this via
        ``parent_field`` wiring."""
        ce.status = "deleted"
        ce.save(update_fields=["status"])
        mfr.status = "deleted"
        mfr.save(update_fields=["status"])
        client.force_login(user)
        resp = _post_restore(client, ce.slug)
        assert resp.status_code == 422


# ── Delete preview ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeletePreview:
    def test_preview_returns_counts(self, client, user, ce, mfr):
        client.force_login(user)
        resp = _get_preview(client, ce.slug)
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == ce.slug
        assert body["blocked_by"] == []
        # Regression guard: CE was registered with parent_field="manufacturer",
        # so the preview must surface the parent so the UI can redirect back
        # to the manufacturer after delete (mirroring Model → Title UX).
        assert body["parent"] == {"name": mfr.name, "public_id": mfr.public_id}

    def test_preview_surfaces_blockers(self, client, user, bootstrap_source, ce):
        _make_model(bootstrap_source, ce, "mm-pro")
        client.force_login(user)
        resp = _get_preview(client, ce.slug)
        assert resp.status_code == 200
        assert resp.json()["blocked_by"]
