"""End-to-end tests for Manufacturer delete, delete-preview, and restore.

Manufacturer delete/restore is plain ``register_entity_delete_restore``.
``plan_soft_delete`` walks PROTECT referrers and surfaces both active
``CorporateEntity.manufacturer`` and active ``System.manufacturer`` blockers.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.catalog.models import CorporateEntity, Manufacturer, System
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction
from apps.provenance.test_factories import make_claim, user_changeset

User = get_user_model()


@pytest.fixture
def mfr(db, bootstrap_source):
    m = Manufacturer.objects.create(name="Stern", slug="stern", status="active")
    make_claim(m, "name", "Stern", source=bootstrap_source)
    make_claim(m, "status", "active", source=bootstrap_source)
    return m


def _make_ce(
    bootstrap_source, mfr, slug: str, *, status: str = "active"
) -> CorporateEntity:
    ce = CorporateEntity.objects.create(
        name=slug.replace("-", " ").title(),
        slug=slug,
        manufacturer=mfr,
        status=status,
    )
    make_claim(ce, "name", ce.name, source=bootstrap_source)
    return ce


def _make_system(bootstrap_source, mfr, slug: str, *, status: str = "active") -> System:
    s = System.objects.create(
        name=slug.replace("-", " ").title(),
        slug=slug,
        manufacturer=mfr,
        status=status,
    )
    make_claim(s, "name", s.name, source=bootstrap_source)
    return s


def _post_delete(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/manufacturers/{slug}/delete/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _post_restore(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/manufacturers/{slug}/restore/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _get_preview(client, slug: str):
    return client.get(f"/api/manufacturers/{slug}/delete-preview/")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAuth:
    def test_anonymous_rejected(self, client, mfr):
        resp = _post_delete(client, "stern")
        assert resp.status_code in (401, 403)
        assert Manufacturer.objects.get(slug="stern").status == "active"

    def test_preview_requires_auth(self, client, mfr):
        assert _get_preview(client, "stern").status_code in (401, 403)


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteHappyPath:
    def test_deletes_bare_manufacturer(self, client, user, mfr):
        client.force_login(user)
        resp = _post_delete(client, "stern", {"note": "bye"})
        assert resp.status_code == 200, resp.content

        mfr.refresh_from_db()
        assert mfr.status == "deleted"

        cs = ChangeSet.objects.get(pk=resp.json()["changeset_id"])
        assert cs.user_id == user.pk
        assert cs.action == ChangeSetAction.DELETE
        assert cs.note == "bye"


# ── PROTECT blockers: CorporateEntity and System ────────────────────


@pytest.mark.django_db
class TestDeletePROTECTBlockers:
    def test_active_ce_blocks(self, client, user, bootstrap_source, mfr):
        _make_ce(bootstrap_source, mfr, "stern-ce")
        client.force_login(user)
        resp = _post_delete(client, "stern")
        assert resp.status_code == 422
        assert resp.json()["blocked_by"]
        mfr.refresh_from_db()
        assert mfr.status == "active"

    def test_active_system_blocks(self, client, user, bootstrap_source, mfr):
        _make_system(bootstrap_source, mfr, "spike")
        client.force_login(user)
        resp = _post_delete(client, "stern")
        assert resp.status_code == 422
        assert resp.json()["blocked_by"]
        mfr.refresh_from_db()
        assert mfr.status == "active"

    def test_deleted_referrers_do_not_block(self, client, user, bootstrap_source, mfr):
        """Soft-deleted referrers don't block — ``plan_soft_delete`` skips
        them when walking usage references."""
        _make_ce(bootstrap_source, mfr, "zombie-ce", status="deleted")
        _make_system(bootstrap_source, mfr, "zombie-sys", status="deleted")
        client.force_login(user)
        resp = _post_delete(client, "stern")
        assert resp.status_code == 200, resp.content
        mfr.refresh_from_db()
        assert mfr.status == "deleted"


# ── Already deleted ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteIdempotence:
    def test_already_deleted_returns_404(self, client, user, mfr):
        mfr.status = "deleted"
        mfr.save(update_fields=["status"])
        client.force_login(user)
        resp = _post_delete(client, "stern")
        assert resp.status_code == 404


# ── Delete preview ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeletePreview:
    def test_preview_returns_counts(self, client, user, bootstrap_source, mfr):
        # Route through the factory so the seed changeset carries an actor.
        cs = user_changeset(user, note="seed")
        make_claim(mfr, "description", "hi", changeset=cs)
        client.force_login(user)
        resp = _get_preview(client, "stern")
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == "stern"
        assert body["changeset_count"] >= 1
        assert body["blocked_by"] == []

    def test_preview_surfaces_blockers(self, client, user, bootstrap_source, mfr):
        _make_ce(bootstrap_source, mfr, "stern-ce")
        client.force_login(user)
        resp = _get_preview(client, "stern")
        assert resp.status_code == 200
        assert resp.json()["blocked_by"]


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRestore:
    def test_restores_status_active(self, client, user, mfr):
        client.force_login(user)
        _post_delete(client, "stern")
        mfr.refresh_from_db()
        assert mfr.status == "deleted"

        resp = _post_restore(client, "stern")
        assert resp.status_code == 200, resp.content
        mfr.refresh_from_db()
        assert mfr.status == "active"

    def test_restore_rejects_active(self, client, user, mfr):
        client.force_login(user)
        resp = _post_restore(client, "stern")
        assert resp.status_code == 422


# ── Undo ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUndoDelete:
    def test_undo_restores_manufacturer(self, client, user, mfr):
        client.force_login(user)
        cs_id = _post_delete(client, "stern").json()["changeset_id"]

        undo = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({"note": "oops"}),
            content_type="application/json",
        )
        assert undo.status_code == 200, undo.content

        mfr.refresh_from_db()
        assert mfr.status == "active"
