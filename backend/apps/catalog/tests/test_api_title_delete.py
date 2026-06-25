"""End-to-end tests for the Title delete, delete-preview, and restore endpoints."""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.accounts.test_factories import make_user
from apps.catalog.models import MachineModel, Title
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim, Source
from apps.provenance.test_factories import make_claim, user_changeset


@pytest.fixture
def bootstrap_source(db):
    """Low-priority source; seeds name claims so the resolver doesn't blank
    ``name`` when a status claim is written during the delete path."""
    return Source.objects.create(
        name="Bootstrap", slug="bootstrap", source_type="editorial", priority=1
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_title(bootstrap_source, slug: str, name: str | None = None) -> Title:
    label = name or slug.replace("-", " ").title()
    t = Title.objects.create(name=label, slug=slug, status="active")
    # Seed name + status claims from a low-priority source so the resolver
    # has something to fall back to after an undo deactivates the user's
    # status claim. Mirrors what ingest would provide in production.
    make_claim(t, "name", label, source=bootstrap_source)
    make_claim(t, "status", "active", source=bootstrap_source)
    return t


def _make_model(bootstrap_source, title: Title, slug: str) -> MachineModel:
    label = slug.replace("-", " ").title()
    m = MachineModel.objects.create(
        title=title,
        name=label,
        slug=slug,
        status="active",
    )
    make_claim(m, "name", label, source=bootstrap_source)
    make_claim(m, "status", "active", source=bootstrap_source)
    return m


def _post_delete(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/titles/{slug}/delete/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _post_restore(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/titles/{slug}/restore/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _get_preview(client, slug: str):
    return client.get(f"/api/titles/{slug}/delete-preview/")


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAuth:
    def test_anonymous_rejected(self, client, bootstrap_source):
        _make_title(bootstrap_source, "g")
        resp = _post_delete(client, "g")
        assert resp.status_code in (401, 403)
        assert Title.objects.get(slug="g").status == "active"

    def test_preview_requires_auth(self, client, bootstrap_source):
        """The preview endpoint is auth-gated so impact counts don't leak."""
        _make_title(bootstrap_source, "g")
        resp = _get_preview(client, "g")
        assert resp.status_code in (401, 403)

    def test_restore_requires_auth(self, client, bootstrap_source):
        t = _make_title(bootstrap_source, "g")
        t.status = "deleted"
        t.save(update_fields=["status"])
        resp = _post_restore(client, "g")
        assert resp.status_code in (401, 403)
        t.refresh_from_db()
        assert t.status == "deleted"


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteHappyPath:
    def test_deletes_lone_title(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "lonely")
        client.force_login(user)
        resp = _post_delete(client, "lonely", {"note": "bye"})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["affected_titles"] == ["lonely"]
        assert body["affected_models"] == []

        t.refresh_from_db()
        assert t.status == "deleted"

        cs = ChangeSet.objects.get(pk=body["changeset_id"])
        assert cs.user_id == user.pk
        assert cs.action == ChangeSetAction.DELETE
        assert cs.note == "bye"

    def test_cascades_to_active_models(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        le = _make_model(bootstrap_source, t, "mm-le")
        client.force_login(user)

        resp = _post_delete(client, "mm")
        assert resp.status_code == 200
        body = resp.json()
        assert body["affected_titles"] == ["mm"]
        assert set(body["affected_models"]) == {"mm-pro", "mm-le"}

        t.refresh_from_db()
        pro.refresh_from_db()
        le.refresh_from_db()
        assert t.status == "deleted"
        assert pro.status == "deleted"
        assert le.status == "deleted"

        # One delete ChangeSet covers the entire cascade.
        cs = ChangeSet.objects.get(pk=body["changeset_id"])
        field_names = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert field_names == {"status"}
        assert cs.claims.count() == 3

    def test_already_deleted_child_not_re_touched(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        active = _make_model(bootstrap_source, t, "mm-pro")
        MachineModel.objects.create(
            title=t, name="MM LE", slug="mm-le-zombie", status="deleted"
        )
        client.force_login(user)
        resp = _post_delete(client, "mm")
        assert resp.status_code == 200
        body = resp.json()
        # The cascade only touches the title and its already-active model.
        assert body["affected_models"] == ["mm-pro"]
        active.refresh_from_db()
        assert active.status == "deleted"

    def test_detail_becomes_404_after_delete(self, client, user, bootstrap_source):
        _make_title(bootstrap_source, "g")
        client.force_login(user)
        _post_delete(client, "g")
        assert client.get("/api/titles/g/").status_code == 404


# ── Blocked path ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteBlocked:
    def test_cross_title_variant_blocks(self, client, user, bootstrap_source):
        other = _make_title(bootstrap_source, "other")
        target = _make_title(bootstrap_source, "target")
        pro = _make_model(bootstrap_source, target, "target-pro")
        MachineModel.objects.create(
            title=other,
            name="Other Variant",
            slug="other-variant",
            status="active",
            variant_of=pro,
        )
        client.force_login(user)
        resp = _post_delete(client, "target")
        assert resp.status_code == 422
        body = resp.json()
        blocked = body["blocked_by"]
        assert len(blocked) == 1
        assert blocked[0]["slug"] == "other-variant"
        assert blocked[0]["relation"] == "variant_of"

        target.refresh_from_db()
        assert target.status == "active"


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteRateLimit:
    def test_sixth_delete_returns_429(self, client, user, settings, bootstrap_source):
        client.force_login(user)
        for i in range(5):
            _make_title(bootstrap_source, f"t{i}")
            resp = _post_delete(client, f"t{i}")
            assert resp.status_code == 200, resp.content
        _make_title(bootstrap_source, "overflow")
        resp = _post_delete(client, "overflow")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_staff_exempt(self, client, staff, bootstrap_source):
        client.force_login(staff)
        for i in range(10):
            _make_title(bootstrap_source, f"t{i}")
            resp = _post_delete(client, f"t{i}")
            assert resp.status_code == 200


# ── Delete preview ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeletePreview:
    def test_returns_counts(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        _make_model(bootstrap_source, t, "mm-pro")
        _make_model(bootstrap_source, t, "mm-le")
        # Stamp a user changeset (via the factory so it carries an actor)
        # touching the title so changeset_count > 0.
        cs = user_changeset(user, note="seed")
        make_claim(t, "name", "Medieval Madness", changeset=cs)
        client.force_login(user)
        resp = _get_preview(client, "mm")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == t.name
        assert body["active_model_count"] == 2
        assert body["changeset_count"] >= 1
        assert body["blocked_by"] == []

    def test_preview_shows_blockers(self, client, user, bootstrap_source):
        other = _make_title(bootstrap_source, "other")
        target = _make_title(bootstrap_source, "target")
        pro = _make_model(bootstrap_source, target, "target-pro")
        MachineModel.objects.create(
            title=other,
            name="Other Variant",
            slug="other-variant",
            status="active",
            variant_of=pro,
        )
        client.force_login(user)
        resp = _get_preview(client, "target")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        assert body["blocked_by"][0]["slug"] == "other-variant"


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRestore:
    def test_restores_status_active(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "g")
        # First delete it (via the endpoint so the fixture's status field
        # reflects the resolved value).
        client.force_login(user)
        _post_delete(client, "g")
        t.refresh_from_db()
        assert t.status == "deleted"

        resp = _post_restore(client, "g")
        assert resp.status_code == 200, resp.content
        t.refresh_from_db()
        assert t.status == "active"

    def test_restore_rejects_active_title(self, client, user, bootstrap_source):
        _make_title(bootstrap_source, "g")
        client.force_login(user)
        resp = _post_restore(client, "g")
        assert resp.status_code == 422

    def test_restore_does_not_bring_child_models_back(
        self, client, user, bootstrap_source
    ):
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        client.force_login(user)
        _post_delete(client, "mm")
        m.refresh_from_db()
        assert m.status == "deleted"

        resp = _post_restore(client, "mm")
        assert resp.status_code == 200
        m.refresh_from_db()
        # Restore is "fresh status=active on the Title only" — Undo is the
        # path that brings cascaded children back in one action.
        assert m.status == "deleted"


# ── Undo ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUndoDelete:
    def test_undo_restores_title_and_children(self, client, user, bootstrap_source):
        t = _make_title(bootstrap_source, "mm")
        pro = _make_model(bootstrap_source, t, "mm-pro")
        le = _make_model(bootstrap_source, t, "mm-le")
        client.force_login(user)

        resp = _post_delete(client, "mm")
        assert resp.status_code == 200
        cs_id = resp.json()["changeset_id"]

        undo = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({"note": "oops"}),
            content_type="application/json",
        )
        assert undo.status_code == 200, undo.content

        t.refresh_from_db()
        pro.refresh_from_db()
        le.refresh_from_db()
        assert t.status == "active"
        assert pro.status == "active"
        assert le.status == "active"

    def test_undo_by_other_user_forbidden(self, client, user, db, bootstrap_source):
        other = make_user()
        _make_title(bootstrap_source, "g")
        client.force_login(user)
        cs_id = _post_delete(client, "g").json()["changeset_id"]

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
        """An edit on the title after delete invalidates Undo of the delete."""
        _make_title(bootstrap_source, "g")
        client.force_login(user)
        cs_id = _post_delete(client, "g").json()["changeset_id"]

        # Restore writes a newer status=active claim, superseding the
        # status=deleted claim inside the DELETE ChangeSet.
        _post_restore(client, "g")

        resp = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 422
