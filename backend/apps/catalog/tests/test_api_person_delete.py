"""End-to-end tests for Person delete, delete-preview, and restore endpoints.

Shares the Title/Model delete structure but adds the Person-specific
credit-blocker branch: a Person cannot be soft-deleted while credited on
any active Model or Series. Credits on already-soft-deleted parents don't
count — matching the PROTECT policy used for lifecycle-entity referrers.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache

from apps.catalog.models import Credit, CreditRole, MachineModel, Person, Series, Title
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction
from apps.provenance.test_factories import make_claim, user_changeset


@pytest.fixture
def design_role(db):
    return CreditRole.objects.create(slug="design", name="Design", display_order=10)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_person(bootstrap_source, slug: str, name: str | None = None) -> Person:
    label = name or slug.replace("-", " ").title()
    p = Person.objects.create(name=label, slug=slug, status="active")
    make_claim(p, "name", label, source=bootstrap_source)
    make_claim(p, "status", "active", source=bootstrap_source)
    return p


def _make_title(bootstrap_source, slug: str) -> Title:
    label = slug.replace("-", " ").title()
    t = Title.objects.create(name=label, slug=slug, status="active")
    make_claim(t, "name", label, source=bootstrap_source)
    return t


def _make_model(
    bootstrap_source, title: Title, slug: str, *, status: str = "active"
) -> MachineModel:
    label = slug.replace("-", " ").title()
    m = MachineModel.objects.create(title=title, name=label, slug=slug, status=status)
    make_claim(m, "name", label, source=bootstrap_source)
    return m


def _post_delete(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/people/{slug}/delete/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _post_restore(client, slug: str, body: JsonBody | None = None):
    return client.post(
        f"/api/people/{slug}/restore/",
        data=json.dumps(body or {}),
        content_type="application/json",
    )


def _get_preview(client, slug: str):
    return client.get(f"/api/people/{slug}/delete-preview/")


# ── Auth ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAuth:
    def test_anonymous_rejected(self, client, bootstrap_source):
        _make_person(bootstrap_source, "pat-lawlor")
        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code in (401, 403)
        assert Person.objects.get(slug="pat-lawlor").status == "active"

    def test_preview_requires_auth(self, client, bootstrap_source):
        _make_person(bootstrap_source, "pat-lawlor")
        resp = _get_preview(client, "pat-lawlor")
        assert resp.status_code in (401, 403)

    def test_restore_requires_auth(self, client, bootstrap_source):
        p = _make_person(bootstrap_source, "pat-lawlor")
        p.status = "deleted"
        p.save(update_fields=["status"])
        resp = _post_restore(client, "pat-lawlor")
        assert resp.status_code in (401, 403)
        p.refresh_from_db()
        assert p.status == "deleted"


# ── Happy path ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteHappyPath:
    def test_deletes_person_with_no_credits(self, client, user, bootstrap_source):
        p = _make_person(bootstrap_source, "pat-lawlor")
        client.force_login(user)

        resp = _post_delete(client, "pat-lawlor", {"note": "bye"})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["affected_slugs"] == ["pat-lawlor"]

        p.refresh_from_db()
        assert p.status == "deleted"

        cs = ChangeSet.objects.get(pk=body["changeset_id"])
        assert cs.user_id == user.pk
        assert cs.action == ChangeSetAction.DELETE
        assert cs.note == "bye"
        # Single status claim; Person has no lifecycle children to cascade.
        assert cs.claims.count() == 1
        first_claim = cs.claims.first()
        assert first_claim is not None
        assert first_claim.field_name == "status"

    def test_detail_becomes_404_after_delete(self, client, user, bootstrap_source):
        _make_person(bootstrap_source, "pat-lawlor")
        client.force_login(user)
        _post_delete(client, "pat-lawlor")
        assert client.get("/api/pages/person/pat-lawlor").status_code == 404


# ── Credit blocker ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteCreditBlocker:
    def test_active_model_credit_blocks(
        self, client, user, bootstrap_source, design_role
    ):
        p = _make_person(bootstrap_source, "pat-lawlor")
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        Credit.objects.create(person=p, model=m, role=design_role)
        client.force_login(user)

        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code == 422
        body = resp.json()
        assert body["active_credit_count"] == 1
        assert "credited on 1 active machine" in body["detail"]

        p.refresh_from_db()
        assert p.status == "active"

    def test_multiple_credits_block(self, client, user, bootstrap_source, design_role):
        p = _make_person(bootstrap_source, "pat-lawlor")
        t = _make_title(bootstrap_source, "mm")
        for i in range(3):
            m = _make_model(bootstrap_source, t, f"mm-{i}")
            Credit.objects.create(person=p, model=m, role=design_role)
        client.force_login(user)

        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code == 422
        assert resp.json()["active_credit_count"] == 3
        assert "3 active machines" in resp.json()["detail"]

    def test_deleted_model_credits_do_not_block(
        self, client, user, bootstrap_source, design_role
    ):
        """Matches the PROTECT policy: references from soft-deleted entities
        don't count as active blockers."""
        p = _make_person(bootstrap_source, "pat-lawlor")
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro", status="deleted")
        Credit.objects.create(person=p, model=m, role=design_role)
        client.force_login(user)

        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code == 200, resp.content
        p.refresh_from_db()
        assert p.status == "deleted"

    def test_active_series_credit_blocks(
        self, client, user, bootstrap_source, design_role
    ):
        p = _make_person(bootstrap_source, "pat-lawlor")
        series = Series.objects.create(
            name="Star Wars Series", slug="star-wars-series", status="active"
        )
        make_claim(series, "name", "Star Wars Series", source=bootstrap_source)
        Credit.objects.create(person=p, series=series, role=design_role)
        client.force_login(user)

        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code == 422
        assert resp.json()["active_credit_count"] == 1

    def test_mixed_active_and_deleted_credits_count_only_active(
        self, client, user, bootstrap_source, design_role
    ):
        p = _make_person(bootstrap_source, "pat-lawlor")
        t = _make_title(bootstrap_source, "mm")
        active_m = _make_model(bootstrap_source, t, "mm-pro")
        deleted_m = _make_model(bootstrap_source, t, "mm-zombie", status="deleted")
        Credit.objects.create(person=p, model=active_m, role=design_role)
        Credit.objects.create(person=p, model=deleted_m, role=design_role)
        client.force_login(user)

        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code == 422
        assert resp.json()["active_credit_count"] == 1


# ── Already deleted ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteIdempotence:
    def test_already_deleted_returns_404(self, client, user, bootstrap_source):
        p = _make_person(bootstrap_source, "pat-lawlor")
        p.status = "deleted"
        p.save(update_fields=["status"])
        client.force_login(user)

        # The endpoint fetches Person.objects.active(), so soft-deleted rows
        # are invisible and the response is 404.
        resp = _post_delete(client, "pat-lawlor")
        assert resp.status_code == 404


# ── Rate limiting ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteRateLimit:
    def test_sixth_delete_returns_429(self, client, user, bootstrap_source):
        client.force_login(user)
        for i in range(5):
            _make_person(bootstrap_source, f"person-{i}")
            resp = _post_delete(client, f"person-{i}")
            assert resp.status_code == 200, resp.content
        _make_person(bootstrap_source, "overflow")
        resp = _post_delete(client, "overflow")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_staff_exempt(self, client, staff, bootstrap_source):
        client.force_login(staff)
        for i in range(10):
            _make_person(bootstrap_source, f"person-{i}")
            resp = _post_delete(client, f"person-{i}")
            assert resp.status_code == 200, resp.content


# ── Delete preview ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeletePreview:
    def test_returns_counts_without_blockers(self, client, user, bootstrap_source):
        p = _make_person(bootstrap_source, "pat-lawlor")
        # Route through the factory so the seed changeset carries an actor.
        cs = user_changeset(user, note="seed")
        make_claim(p, "birth_place", "Chicago", changeset=cs)
        client.force_login(user)

        resp = _get_preview(client, "pat-lawlor")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == p.name
        assert body["slug"] == "pat-lawlor"
        assert body["active_credit_count"] == 0
        assert body["changeset_count"] >= 1
        assert body["blocked_by"] == []

    def test_preview_surfaces_credit_block(
        self, client, user, bootstrap_source, design_role
    ):
        p = _make_person(bootstrap_source, "pat-lawlor")
        t = _make_title(bootstrap_source, "mm")
        m = _make_model(bootstrap_source, t, "mm-pro")
        Credit.objects.create(person=p, model=m, role=design_role)
        client.force_login(user)

        resp = _get_preview(client, "pat-lawlor")
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_credit_count"] == 1
        # changeset_count is suppressed when blocked — the UI hides it.
        assert body["changeset_count"] == 0


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRestore:
    def test_restores_status_active(self, client, user, bootstrap_source):
        p = _make_person(bootstrap_source, "pat-lawlor")
        client.force_login(user)
        _post_delete(client, "pat-lawlor")
        p.refresh_from_db()
        assert p.status == "deleted"

        resp = _post_restore(client, "pat-lawlor")
        assert resp.status_code == 200, resp.content
        p.refresh_from_db()
        assert p.status == "active"

    def test_restore_rejects_active_person(self, client, user, bootstrap_source):
        _make_person(bootstrap_source, "pat-lawlor")
        client.force_login(user)
        resp = _post_restore(client, "pat-lawlor")
        assert resp.status_code == 422


# ── Undo ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUndoDelete:
    def test_undo_restores_person(self, client, user, bootstrap_source):
        p = _make_person(bootstrap_source, "pat-lawlor")
        client.force_login(user)
        cs_id = _post_delete(client, "pat-lawlor").json()["changeset_id"]

        undo = client.post(
            f"/api/changesets/{cs_id}/undo/",
            data=json.dumps({"note": "oops"}),
            content_type="application/json",
        )
        assert undo.status_code == 200, undo.content

        p.refresh_from_db()
        assert p.status == "active"
