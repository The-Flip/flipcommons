"""Smoke tests for PATCH /api/themes/{public_id}/claims/."""

import json

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Theme
from apps.provenance.models import ChangeSet

User = get_user_model()


@pytest.fixture
def theme(db):
    return Theme.objects.create(name="Sports", slug="sports")


@pytest.fixture
def parent_theme(db):
    return Theme.objects.create(name="Competition", slug="competition")


def _patch(client, slug, body):
    return client.patch(
        f"/api/themes/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


@pytest.mark.django_db
class TestPatchThemeClaims:
    def test_anonymous_gets_401(self, client, theme):
        resp = _patch(client, theme.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code in (401, 403)

    def test_scalar_edit(self, client, user, theme):
        client.force_login(user)
        resp = _patch(client, theme.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code == 200
        assert resp.json()["description"]["text"] == "Updated"

    def test_add_parent(self, client, user, theme, parent_theme):
        client.force_login(user)
        resp = _patch(client, theme.slug, {"parents": ["competition"]})
        assert resp.status_code == 200
        assert [p["public_id"] for p in resp.json()["parents"]] == ["competition"]

    def test_remove_parent(self, client, user, theme, parent_theme):
        client.force_login(user)
        _patch(client, theme.slug, {"parents": ["competition"]})
        resp = _patch(client, theme.slug, {"parents": []})
        assert resp.status_code == 200
        assert resp.json()["parents"] == []

    def test_cycle_rejected(self, client, user, theme, parent_theme):
        client.force_login(user)
        _patch(client, parent_theme.slug, {"parents": ["sports"]})
        resp = _patch(client, theme.slug, {"parents": ["competition"]})
        assert resp.status_code == 422

    def test_changeset_created(self, client, user, theme):
        client.force_login(user)
        _patch(
            client,
            theme.slug,
            {"fields": {"description": "Updated"}, "note": "Test note"},
        )
        assert ChangeSet.objects.count() == 1
        cs = ChangeSet.objects.first()
        assert cs is not None
        assert cs.note == "Test note"
        assert cs.claims.count() == 1


@pytest.mark.django_db
class TestPatchThemeAliases:
    def test_add_aliases(self, client, user, theme):
        client.force_login(user)
        resp = _patch(client, theme.slug, {"aliases": ["Athletics", "Sport"]})
        assert resp.status_code == 200
        assert sorted(resp.json()["aliases"]) == ["Athletics", "Sport"]

    def test_remove_aliases(self, client, user, theme):
        client.force_login(user)
        _patch(client, theme.slug, {"aliases": ["Athletics"]})
        resp = _patch(client, theme.slug, {"aliases": []})
        assert resp.status_code == 200
        assert resp.json()["aliases"] == []

    def test_display_case_preserved(self, client, user, theme):
        client.force_login(user)
        resp = _patch(client, theme.slug, {"aliases": ["eSports"]})
        assert "eSports" in resp.json()["aliases"]
        theme.refresh_from_db()
        assert theme.aliases.get().value == "eSports"

    def test_display_case_update(self, client, user, theme):
        client.force_login(user)
        _patch(client, theme.slug, {"aliases": ["esports"]})
        resp = _patch(client, theme.slug, {"aliases": ["eSports"]})
        assert resp.status_code == 200
        theme.refresh_from_db()
        assert theme.aliases.get().value == "eSports"
