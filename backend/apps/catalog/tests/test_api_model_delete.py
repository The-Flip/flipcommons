"""End-to-end tests for the Model delete, delete-preview, and restore endpoints.

Mirrors ``test_api_title_delete.py`` in structure. Model Delete differs in
that it never cascades — in either direction — so every test either touches
a single Model or verifies that a neighboring entity is left alone.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.accounts.test_factories import make_user
from apps.catalog.models import MachineModel, Title
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction
from apps.provenance.test_factories import make_claim, user_changeset


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_title(bootstrap_source, slug: str, name: str | None = None) -> Title:
    label = name or slug.replace("-", " ").title()
    t = Title.objects.create(name=label, slug=slug, status="active")
    make_claim(t, "name", label, ingest_source=bootstrap_source)
    make_claim(t, "status", "active", ingest_source=bootstrap_source)
    return t


def _make_model(
    bootstrap_source,
    title: Title,
    slug: str,
    *,
    variant_of: MachineModel | None = None,
    remake_of: MachineModel | None = None,
    export_edition_of: MachineModel | None = None,
) -> MachineModel:
    label = slug.replace("-", " ").title()
    m = MachineModel.objects.create(
        title=title,
        name=label,
        slug=slug,
        status="active",
        variant_of=variant_of,
        remake_of=remake_of,
        export_edition_of=export_edition_of,
    )
    make_claim(m, "name", label, ingest_source=bootstrap_source)
    make_claim(m, "status", "active", ingest_source=bootstrap_source)
    return m


def _post_delete(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/models/{slug}/delete/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _post_restore(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/models/{slug}/restore/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _get_preview(client, slug: str):
    return client.get(f"/api/models/{slug}/delete-preview/")


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAuth:
    def test_anonymous_rejected(self, client, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        resp = _post_delete(client, "mm-pro")
        assert resp.status_code in (401, 403)
        assert MachineModel.objects.get(slug="mm-pro").status == "active"

    def test_preview_requires_auth(self, client, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        resp = _get_preview(client, "mm-pro")
        assert resp.status_code in (401, 403)

    def test_restore_requires_auth(self, client, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        m.status = "deleted"
        m.save(update_fields=["status"])
        resp = _post_restore(client, "mm-pro")
        assert resp.status_code in (401, 403)
        m.refresh_from_db()
        assert m.status == "deleted"


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteHappyPath:
    def test_deletes_lone_model(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)

        resp = _post_delete(client, "mm-pro", {"note": "bye"})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["affected_slugs"] == ["mm-pro"]

        m.refresh_from_db()
        assert m.status == "deleted"

        cs = ChangeSet.objects.get(pk=body["changeset_id"])
        assert cs.actor_id == user.actor_id
        assert cs.action == ChangeSetAction.DELETE
        assert cs.note == "bye"
        # Single status claim; no cascade children.
        assert cs.claims.count() == 1
        first_claim = cs.claims.first()
        assert first_claim is not None
        assert first_claim.field_name == "status"

    def test_parent_title_untouched(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)

        _post_delete(client, "mm-pro")
        t.refresh_from_db()
        # Orphan title stays active — "Create first model" CTA reappears.
        assert t.status == "active"

    def test_detail_becomes_404_after_delete(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        _post_delete(client, "mm-pro")
        assert client.get("/api/models/mm-pro/").status_code == 404

    def test_deleting_one_of_many_leaves_siblings(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        le = _make_model(bootstrap_source, t, "mm-le")
        client.force_login(user)

        _post_delete(client, "mm-pro")
        pro.refresh_from_db()
        le.refresh_from_db()
        assert pro.status == "deleted"
        assert le.status == "active"


# ── Blocked path ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteBlocked:
    def test_active_variant_blocks(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        _make_model(bootstrap_source, t, "mm-le", variant_of=pro)
        client.force_login(user)

        resp = _post_delete(client, "mm-pro")
        assert resp.status_code == 422
        blocked = resp.json()["blocked_by"]
        assert len(blocked) == 1
        assert blocked[0]["public_id"] == "mm-le"
        assert blocked[0]["relation"] == "variant_of"

        pro.refresh_from_db()
        assert pro.status == "active"

    def test_cross_title_variant_blocks(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        other = _make_title(bootstrap_source, "other")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        _make_model(bootstrap_source, other, "other-variant", variant_of=pro)
        client.force_login(user)

        resp = _post_delete(client, "mm-pro")
        assert resp.status_code == 422
        blocked = resp.json()["blocked_by"]
        assert len(blocked) == 1
        assert blocked[0]["public_id"] == "other-variant"

    def test_inbound_relationship_edge_blocks(self, client, user, bootstrap_source):
        # The edge row itself has no lifecycle, so the PROTECT pass skips it —
        # but the edge belongs to a different *active* model, whose page would
        # link a 404 if the target vanished. The usage-blocker channel walks
        # through the edge to that owning source model, exactly like Tag's
        # machine_models blocker — preserving the referential semantics the
        # retired converted_from FK enforced.
        from apps.catalog.models import ModelRelationship

        t = _make_title(bootstrap_source, "source")
        source = _make_model(bootstrap_source, t, "source-game")
        t2 = _make_title(bootstrap_source, "conv")
        conv = _make_model(bootstrap_source, t2, "conv-game")
        ModelRelationship.objects.create(
            machine_model=conv,
            target_machine=source,
            relationship_type="conversion",
            license_status="unknown",
        )
        client.force_login(user)

        resp = _post_delete(client, "source-game")
        assert resp.status_code == 422
        blocked = resp.json()["blocked_by"]
        assert any(
            b["relation"] == "inbound_relationship_sources"
            and b["public_id"] == "conv-game"
            for b in blocked
        )

    def test_soft_deleted_source_edge_does_not_block(
        self, client, user, bootstrap_source
    ):
        # Usage blockers count *active* referrers only: once the source model
        # is itself soft-deleted, its edge no longer pins the target.
        from apps.catalog.models import ModelRelationship

        t = _make_title(bootstrap_source, "source")
        source = _make_model(bootstrap_source, t, "source-game")
        t2 = _make_title(bootstrap_source, "conv")
        conv = _make_model(bootstrap_source, t2, "conv-game")
        ModelRelationship.objects.create(
            machine_model=conv,
            target_machine=source,
            relationship_type="conversion",
            license_status="unknown",
        )
        conv.status = "deleted"
        conv.save(update_fields=["status"])
        client.force_login(user)

        resp = _post_delete(client, "source-game")
        assert resp.status_code == 200

    def test_remake_of_referrer_blocks(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "og")
        og = _make_model(bootstrap_source, t, "og-game")
        t2 = _make_title(bootstrap_source, "new")
        _make_model(bootstrap_source, t2, "new-game", remake_of=og)
        client.force_login(user)

        resp = _post_delete(client, "og-game")
        assert resp.status_code == 422
        blocked = resp.json()["blocked_by"]
        assert any(b["relation"] == "remake_of" for b in blocked)

    def test_export_edition_of_referrer_blocks(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "domestic")
        domestic = _make_model(bootstrap_source, t, "domestic-game")
        t2 = _make_title(bootstrap_source, "export")
        _make_model(bootstrap_source, t2, "export-game", export_edition_of=domestic)
        client.force_login(user)

        resp = _post_delete(client, "domestic-game")
        assert resp.status_code == 422
        blocked = resp.json()["blocked_by"]
        assert any(b["relation"] == "export_edition_of" for b in blocked)

    def test_already_deleted_variant_does_not_block(
        self, client, user, bootstrap_source
    ):
        t = _make_title(bootstrap_source, "mm")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        MachineModel.objects.create(
            title=t,
            name="MM LE (zombie)",
            slug="mm-le-zombie",
            status="deleted",
            variant_of=pro,
        )
        client.force_login(user)

        resp = _post_delete(client, "mm-pro")
        assert resp.status_code == 200, resp.content
        pro.refresh_from_db()
        assert pro.status == "deleted"


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteRateLimit:
    def test_sixth_delete_returns_429(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        client.force_login(user)
        for i in range(5):
            _make_model(bootstrap_source, t, f"mm-{i}")
            resp = _post_delete(client, f"mm-{i}")
            assert resp.status_code == 200, resp.content
        _make_model(bootstrap_source, t, "mm-overflow")
        resp = _post_delete(client, "mm-overflow")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_staff_exempt(self, client, staff, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        client.force_login(staff)
        for i in range(10):
            _make_model(bootstrap_source, t, f"mm-{i}")
            resp = _post_delete(client, f"mm-{i}")
            assert resp.status_code == 200


# ── Delete preview ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeletePreview:
    def test_returns_counts_and_title(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm", name="Medieval Madness")
        m = _make_model(bootstrap_source, t, "mm-pro")
        # Route through the factory so the seed changeset carries an actor.
        cs = user_changeset(user, note="seed")
        make_claim(m, "name", "MM Pro", changeset=cs)
        client.force_login(user)

        resp = _get_preview(client, "mm-pro")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == m.name
        assert body["slug"] == "mm-pro"
        assert body["parent"] == {"name": "Medieval Madness", "public_id": "mm"}
        assert body["changeset_count"] >= 1
        assert body["blocked_by"] == []

    def test_preview_shows_blockers(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        _make_model(bootstrap_source, t, "mm-le", variant_of=pro)
        client.force_login(user)

        resp = _get_preview(client, "mm-pro")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        assert body["blocked_by"][0]["public_id"] == "mm-le"


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRestore:
    def test_restores_status_active(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        _post_delete(client, "mm-pro")
        m.refresh_from_db()
        assert m.status == "deleted"

        resp = _post_restore(client, "mm-pro")
        assert resp.status_code == 200, resp.content
        m.refresh_from_db()
        assert m.status == "active"

    def test_restore_rejects_active_model(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        resp = _post_restore(client, "mm-pro")
        assert resp.status_code == 422


# ── Undo ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUndoDelete:
    def test_undo_restores_model(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        cs_id = _post_delete(client, "mm-pro").json()["changeset_id"]

        undo = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({"note": "oops"}),
            content_type="application/json",
        )
        assert undo.status_code == 200, undo.content

        m.refresh_from_db()
        assert m.status == "active"

    def test_undo_by_other_user_forbidden(self, client, user, db, bootstrap_source):
        other = make_user()
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        cs_id = _post_delete(client, "mm-pro").json()["changeset_id"]

        client.force_login(other)
        resp = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["kind"] == "policy_denied"
        assert body["detail"]["code"] == "owner_required"
        assert body["detail"]["message"] == "Only the original author can do that."

    def test_undo_rejected_when_superseded(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        cs_id = _post_delete(client, "mm-pro").json()["changeset_id"]

        # Restore writes a newer status=active claim, superseding the delete.
        _post_restore(client, "mm-pro")

        resp = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 422
