"""End-to-end tests for System delete, delete-preview, and restore endpoints.

System delete/restore is plain ``register_entity_delete_restore``:
PROTECT blocking via ``plan_soft_delete`` (active MachineModel referrers
via MachineModel.system), no active-child blockers of its own.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import MachineModel, Manufacturer, System, Title
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction
from apps.provenance.test_factories import make_claim, user_changeset


@pytest.fixture
def mfr(db, bootstrap_source):
    m = Manufacturer.objects.create(name="Stern", slug="stern", status="active")
    make_claim(m, "name", "Stern", source=bootstrap_source)
    return m


def _make_system(bootstrap_source, mfr, slug: str, name: str | None = None) -> System:
    label = name or slug.replace("-", " ").title()
    s = System.objects.create(name=label, slug=slug, manufacturer=mfr, status="active")
    make_claim(s, "name", label, source=bootstrap_source)
    make_claim(s, "status", "active", source=bootstrap_source)
    return s


def _make_model(
    bootstrap_source, slug: str, *, system: System, status: str = "active"
) -> MachineModel:
    title = Title.objects.create(
        name=slug.replace("-", " ").title(), slug=f"{slug}-title", status="active"
    )
    make_claim(title, "name", title.name, source=bootstrap_source)
    m = MachineModel.objects.create(
        title=title,
        name=slug.replace("-", " ").title(),
        slug=slug,
        system=system,
        status=status,
    )
    make_claim(m, "name", m.name, source=bootstrap_source)
    return m


def _post_delete(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/systems/{slug}/delete/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _post_restore(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/systems/{slug}/restore/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _get_preview(client, slug: str):
    return client.get(f"/api/systems/{slug}/delete-preview/")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAuth:
    def test_anonymous_rejected(self, client, bootstrap_source, mfr):
        _make_system(bootstrap_source, mfr, "spike")
        resp = _post_delete(client, "spike")
        assert resp.status_code in (401, 403)
        assert System.objects.get(slug="spike").status == "active"

    def test_preview_requires_auth(self, client, bootstrap_source, mfr):
        _make_system(bootstrap_source, mfr, "spike")
        assert _get_preview(client, "spike").status_code in (401, 403)

    def test_restore_requires_auth(self, client, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        s.status = "deleted"
        s.save(update_fields=["status"])
        resp = _post_restore(client, "spike")
        assert resp.status_code in (401, 403)


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteHappyPath:
    def test_deletes_system_with_no_models(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        client.force_login(user)

        resp = _post_delete(client, "spike", {"note": "bye"})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["affected_slugs"] == ["spike"]

        s.refresh_from_db()
        assert s.status == "deleted"

        cs = ChangeSet.objects.get(pk=body["changeset_id"])
        assert cs.user_id == user.pk
        assert cs.action == ChangeSetAction.DELETE
        assert cs.note == "bye"


# ── PROTECT blocker: active MachineModel referrers ──────────────────


@pytest.mark.django_db
class TestDeletePROTECTBlocker:
    def test_active_model_blocks(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        _make_model(bootstrap_source, "mm-pro", system=s)
        client.force_login(user)

        resp = _post_delete(client, "spike")
        assert resp.status_code == 422
        body = resp.json()
        assert body["blocked_by"], body
        s.refresh_from_db()
        assert s.status == "active"

    def test_deleted_models_do_not_block(self, client, user, bootstrap_source, mfr):
        """PROTECT is DB-level, but ``plan_soft_delete`` filters out
        already soft-deleted referrers per the spec."""
        s = _make_system(bootstrap_source, mfr, "spike")
        _make_model(bootstrap_source, "mm-zombie", system=s, status="deleted")
        client.force_login(user)

        resp = _post_delete(client, "spike")
        assert resp.status_code == 200, resp.content
        s.refresh_from_db()
        assert s.status == "deleted"


# ── Already deleted ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteIdempotence:
    def test_already_deleted_returns_404(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        s.status = "deleted"
        s.save(update_fields=["status"])
        client.force_login(user)

        # The registrar fetches via System.objects.active(); soft-deleted
        # rows are invisible → 404.
        resp = _post_delete(client, "spike")
        assert resp.status_code == 404


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteRateLimit:
    def test_sixth_delete_returns_429(self, client, user, bootstrap_source, mfr):
        client.force_login(user)
        for i in range(5):
            _make_system(bootstrap_source, mfr, f"sys-{i}")
            resp = _post_delete(client, f"sys-{i}")
            assert resp.status_code == 200, resp.content
        _make_system(bootstrap_source, mfr, "overflow")
        resp = _post_delete(client, "overflow")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


# ── Delete preview ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeletePreview:
    def test_returns_counts_without_blockers(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        # Route through the factory so the seed changeset carries an actor.
        cs = user_changeset(user, note="seed")
        make_claim(s, "description", "hi", changeset=cs)
        client.force_login(user)

        resp = _get_preview(client, "spike")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == s.name
        assert body["slug"] == "spike"
        assert body["changeset_count"] >= 1
        assert body["blocked_by"] == []

    def test_preview_surfaces_block(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        _make_model(bootstrap_source, "mm-pro", system=s)
        client.force_login(user)

        resp = _get_preview(client, "spike")
        assert resp.status_code == 200
        body = resp.json()
        assert body["blocked_by"]
        assert body["changeset_count"] == 0


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRestore:
    def test_restores_status_active(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        client.force_login(user)
        _post_delete(client, "spike")
        s.refresh_from_db()
        assert s.status == "deleted"

        resp = _post_restore(client, "spike")
        assert resp.status_code == 200, resp.content
        s.refresh_from_db()
        assert s.status == "active"

    def test_restore_rejects_active_system(self, client, user, bootstrap_source, mfr):
        _make_system(bootstrap_source, mfr, "spike")
        client.force_login(user)
        resp = _post_restore(client, "spike")
        assert resp.status_code == 422


# ── Undo ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUndoDelete:
    def test_undo_restores_system(self, client, user, bootstrap_source, mfr):
        s = _make_system(bootstrap_source, mfr, "spike")
        client.force_login(user)
        cs_id = _post_delete(client, "spike").json()["changeset_id"]

        undo = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({"note": "oops"}),
            content_type="application/json",
        )
        assert undo.status_code == 200, undo.content

        s.refresh_from_db()
        assert s.status == "active"
