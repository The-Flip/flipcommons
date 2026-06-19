"""Credit-role-specific API coverage: CRUD, page endpoint, people list, delete blockers."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.catalog.engine.entity_api.delete import execute_soft_delete
from apps.catalog.models import (
    Credit,
    CreditRole,
    Person,
    Series,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, path: str, body: JsonBody):
    return client.post(path, data=json.dumps(body), content_type="application/json")


# ── List / detail ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreditRoleList:
    def test_returns_active_roles_ordered_by_name(self, client):
        CreditRole.objects.create(
            name="Software", slug="software", display_order=90, status="active"
        )
        CreditRole.objects.create(
            name="Design", slug="design", display_order=10, status="active"
        )
        CreditRole.objects.create(name="Retired", slug="retired", status="deleted")

        resp = client.get("/api/credit-roles/")
        assert resp.status_code == 200
        body = resp.json()
        assert [r["slug"] for r in body["items"]] == ["design", "software"]


@pytest.mark.django_db
class TestCreditRoleDetail:
    def test_returns_detail_with_empty_people_list(self, client):
        CreditRole.objects.create(name="Design", slug="design", status="active")
        resp = client.get("/api/credit-roles/design")
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == "design"
        assert body["people"] == []

    def test_404_on_unknown_slug(self, client, db):
        assert client.get("/api/credit-roles/nope").status_code == 404

    def test_404_on_deleted_role(self, client):
        CreditRole.objects.create(name="Retired", slug="retired", status="deleted")
        assert client.get("/api/credit-roles/retired").status_code == 404


# ── Page endpoint ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreditRolePageEndpoint:
    def test_returns_page_model(self, client):
        CreditRole.objects.create(name="Art", slug="art", status="active")
        resp = client.get("/api/pages/credit-role/art")
        assert resp.status_code == 200
        body = resp.json()
        assert body["slug"] == "art"
        assert body["name"] == "Art"
        assert body["people"] == []

    def test_404(self, client, db):
        assert client.get("/api/pages/credit-role/nope").status_code == 404


# ── People list ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreditRolePeopleList:
    @pytest.fixture
    def role(self, db):
        return CreditRole.objects.create(name="Design", slug="design", status="active")

    @pytest.fixture
    def alice(self, db):
        return Person.objects.create(name="Alice", slug="alice", status="active")

    @pytest.fixture
    def bob(self, db):
        return Person.objects.create(name="Bob", slug="bob", status="active")

    def test_ranks_by_distinct_titles(self, client, role, alice, bob):
        # Alice: 2 distinct titles (one with two variant machines → counts once)
        title_a = Title.objects.create(name="Alpha", slug="alpha")
        title_b = Title.objects.create(name="Beta", slug="beta")
        a_base = make_machine_model(title=title_a, slug="alpha-pro")
        a_le = make_machine_model(title=title_a, slug="alpha-le", variant_of=a_base)
        b = make_machine_model(title=title_b, slug="beta")
        Credit.objects.create(model=a_base, person=alice, role=role)
        Credit.objects.create(model=a_le, person=alice, role=role)
        Credit.objects.create(model=b, person=alice, role=role)

        # Bob: 1 distinct title
        title_c = Title.objects.create(name="Gamma", slug="gamma")
        c = make_machine_model(title=title_c, slug="gamma")
        Credit.objects.create(model=c, person=bob, role=role)

        resp = client.get("/api/credit-roles/design")
        body = resp.json()
        assert [(p["slug"], p["credit_count"]) for p in body["people"]] == [
            ("alice", 2),
            ("bob", 1),
        ]

    def test_excludes_deleted_machines(self, client, role, alice):
        title = Title.objects.create(name="Alpha", slug="alpha")
        active = make_machine_model(title=title, slug="alpha")
        deleted = make_machine_model(
            title=Title.objects.create(name="Beta", slug="beta"),
            slug="beta",
            status="deleted",
        )
        Credit.objects.create(model=active, person=alice, role=role)
        Credit.objects.create(model=deleted, person=alice, role=role)

        resp = client.get("/api/credit-roles/design")
        people = resp.json()["people"]
        assert [(p["slug"], p["credit_count"]) for p in people] == [("alice", 1)]

    def test_excludes_deleted_titles(self, client, role, alice):
        live_title = Title.objects.create(name="Alpha", slug="alpha")
        dead_title = Title.objects.create(name="Beta", slug="beta", status="deleted")
        live = make_machine_model(title=live_title, slug="alpha")
        dead = make_machine_model(title=dead_title, slug="beta")
        Credit.objects.create(model=live, person=alice, role=role)
        Credit.objects.create(model=dead, person=alice, role=role)

        resp = client.get("/api/credit-roles/design")
        people = resp.json()["people"]
        assert [p["credit_count"] for p in people] == [1]

    def test_excludes_deleted_people(self, client, role, alice):
        alice.status = "deleted"
        alice.save(update_fields=["status"])
        title = Title.objects.create(name="Alpha", slug="alpha")
        m = make_machine_model(title=title, slug="alpha")
        Credit.objects.create(model=m, person=alice, role=role)

        resp = client.get("/api/credit-roles/design")
        assert resp.json()["people"] == []

    def test_excludes_series_credits(self, client, role, alice):
        series = Series.objects.create(name="S", slug="s")
        Credit.objects.create(series=series, person=alice, role=role)

        resp = client.get("/api/credit-roles/design")
        assert resp.json()["people"] == []


# ── Create ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreditRoleCreate:
    def test_anonymous_rejected(self, client):
        resp = _post(client, "/api/credit-roles/", {"name": "QA", "slug": "qa"})
        assert resp.status_code in (401, 403)
        assert not CreditRole.objects.filter(slug="qa").exists()

    def test_creates_role_with_claims(self, client, user):
        client.force_login(user)
        resp = _post(client, "/api/credit-roles/", {"name": "QA", "slug": "qa"})
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["slug"] == "qa"
        assert body["people"] == []

        role = CreditRole.objects.get(slug="qa")
        assert role.status == "active"

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_duplicate_name_rejected(self, client, user):
        CreditRole.objects.create(name="QA", slug="qa")
        client.force_login(user)
        resp = _post(client, "/api/credit-roles/", {"name": "QA", "slug": "qa-2"})
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]


# ── Delete blocked by active machine credit ────────────────────────


@pytest.mark.django_db
class TestCreditRoleDeleteBlockedByMachineCredit:
    def test_preview_reports_blocker(self, client, user):
        role = CreditRole.objects.create(name="Design", slug="design", status="active")
        person = Person.objects.create(name="Alice", slug="alice", status="active")
        title = Title.objects.create(name="Alpha", slug="alpha")
        m = make_machine_model(title=title, slug="alpha")
        Credit.objects.create(model=m, person=person, role=role)

        client.force_login(user)
        resp = client.get("/api/credit-roles/design/delete-preview/")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        assert body["blocked_by"][0]["entity_type"] == "model"
        assert body["blocked_by"][0]["slug"] == "alpha"

    def test_delete_blocked(self, client, user):
        role = CreditRole.objects.create(name="Design", slug="design", status="active")
        person = Person.objects.create(name="Alice", slug="alice", status="active")
        title = Title.objects.create(name="Alpha", slug="alpha")
        m = make_machine_model(title=title, slug="alpha")
        Credit.objects.create(model=m, person=person, role=role)

        client.force_login(user)
        resp = _post(client, "/api/credit-roles/design/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert len(body["blocked_by"]) == 1

        role.refresh_from_db()
        assert role.status == "active"

    def test_deleting_machine_unblocks(self, client, user):
        role = CreditRole.objects.create(name="Design", slug="design", status="active")
        person = Person.objects.create(name="Alice", slug="alice", status="active")
        title = Title.objects.create(name="Alpha", slug="alpha")
        m = make_machine_model(title=title, slug="alpha")
        Credit.objects.create(model=m, person=person, role=role)
        # Soft-delete the machine the same way a user would — writes a
        # status=deleted claim that materializes back to the row.
        execute_soft_delete(m, user=user)

        client.force_login(user)
        resp = _post(client, "/api/credit-roles/design/delete/", {})
        assert resp.status_code == 200, resp.content
        role.refresh_from_db()
        assert role.status == "deleted"


# ── Delete blocked by active series credit ─────────────────────────


@pytest.mark.django_db
class TestCreditRoleDeleteBlockedBySeriesCredit:
    def test_series_credit_blocks_delete(self, client, user):
        role = CreditRole.objects.create(name="Design", slug="design", status="active")
        person = Person.objects.create(name="Alice", slug="alice", status="active")
        series = Series.objects.create(name="S", slug="s")
        Credit.objects.create(series=series, person=person, role=role)

        client.force_login(user)
        resp = _post(client, "/api/credit-roles/design/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert len(body["blocked_by"]) == 1
        assert body["blocked_by"][0]["entity_type"] == "series"


# ── Delete unblocked (unused role) ─────────────────────────────────


@pytest.mark.django_db
class TestCreditRoleDeleteUnblocked:
    def test_delete_unused_role_succeeds(self, client, user):
        role = CreditRole.objects.create(name="Unused", slug="unused", status="active")
        client.force_login(user)

        preview = client.get("/api/credit-roles/unused/delete-preview/").json()
        assert preview["blocked_by"] == []

        resp = _post(client, "/api/credit-roles/unused/delete/", {})
        assert resp.status_code == 200, resp.content
        role.refresh_from_db()
        assert role.status == "deleted"

        cs = ChangeSet.objects.get(pk=resp.json()["changeset_id"])
        assert cs.action == ChangeSetAction.DELETE


# ── Restore ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreditRoleRestore:
    def test_restores_deleted_role(self, client, user):
        role = CreditRole.objects.create(
            name="Retired", slug="retired", status="deleted"
        )
        client.force_login(user)
        resp = _post(client, "/api/credit-roles/retired/restore/", {})
        assert resp.status_code == 200, resp.content
        role.refresh_from_db()
        assert role.status == "active"


# ── Edit history routing ────────────────────────────────────────────


@pytest.mark.django_db
class TestCreditRoleEditHistory:
    def test_entity_type_routes_correctly(self, client, user):
        role = CreditRole.objects.create(name="Design", slug="design")

        client.force_login(user)
        client.patch(
            f"/api/credit-roles/{role.slug}/claims/",
            data=json.dumps({"fields": {"description": "Updated copy"}}),
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/credit-role/{role.slug}/")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert len(body) == 1
        entry = body[0]
        assert entry["attribution"]["author"] == {
            "kind": "user",
            "username": user.username,
        }
        # The PATCH we issued edits the description field.
        assert [c["field_name"] for c in entry["changes"]] == ["description"]
