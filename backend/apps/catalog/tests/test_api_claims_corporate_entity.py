"""Tests for CorporateEntity API endpoints."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import (
    CorporateEntity,
    Manufacturer,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import ChangeSet, Claim

User = get_user_model()


@pytest.fixture
def mfr(db, _bootstrap_source):
    m = Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")
    Claim.objects.assert_claim(m, "name", "Gottlieb", source=_bootstrap_source)
    return m


@pytest.fixture
def entity(db, mfr, _bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="D. Gottlieb & Company",
        slug="d-gottlieb-company",
        manufacturer=mfr,
        year_start=1927,
        year_end=1983,
    )
    Claim.objects.assert_claim(
        ce, "name", "D. Gottlieb & Company", source=_bootstrap_source
    )
    return ce


@pytest.fixture
def other_entity(db, mfr, _bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="Mylstar Electronics",
        slug="mylstar-electronics",
        manufacturer=mfr,
        year_start=1983,
        year_end=1984,
    )
    Claim.objects.assert_claim(
        ce, "name", "Mylstar Electronics", source=_bootstrap_source
    )
    return ce


def _patch(client, slug, body):
    return client.patch(
        f"/api/corporate-entities/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestListCorporateEntities:
    def test_list_returns_entities(self, client, entity, other_entity):
        resp = client.get("/api/corporate-entities/")
        assert resp.status_code == 200
        data = resp.json()["items"]
        assert len(data) == 2
        names = [e["name"] for e in data]
        assert "D. Gottlieb & Company" in names
        assert "Mylstar Electronics" in names

    def test_list_includes_manufacturer(self, client, entity):
        resp = client.get("/api/corporate-entities/")
        data = resp.json()["items"]
        assert data[0]["manufacturer"]["name"] == "Gottlieb"
        assert data[0]["manufacturer"]["public_id"] == "gottlieb"

    def test_list_includes_model_count(self, client, entity):
        make_machine_model(
            name="Ace High", slug="ace-high", corporate_entity=entity, year=1957
        )
        resp = client.get("/api/corporate-entities/")
        assert resp.json()["items"][0]["model_count"] == 1

    def test_list_excludes_variants_from_count(self, client, entity):
        base = make_machine_model(
            name="Ace High", slug="ace-high", corporate_entity=entity
        )
        make_machine_model(
            name="Ace High LE",
            slug="ace-high-le",
            corporate_entity=entity,
            variant_of=base,
        )
        resp = client.get("/api/corporate-entities/")
        assert resp.json()["items"][0]["model_count"] == 1


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetCorporateEntity:
    def test_detail_returns_entity(self, client, entity):
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "D. Gottlieb & Company"
        assert data["year_start"] == 1927
        assert data["year_end"] == 1983
        assert data["manufacturer"]["name"] == "Gottlieb"

    def test_detail_includes_ipdb_manufacturer_id(self, client, entity):
        entity.ipdb_manufacturer_id = 77
        entity.save()
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        assert resp.status_code == 200
        assert resp.json()["ipdb_manufacturer_id"] == 77

    def test_detail_includes_aliases(self, client, entity):
        entity.aliases.create(value="Gottlieb Co")
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        assert "Gottlieb Co" in resp.json()["aliases"]

    def test_detail_includes_titles(self, client, entity):
        title = Title.objects.create(name="Ace High", slug="ace-high")
        make_machine_model(
            name="Ace High",
            slug="ace-high",
            corporate_entity=entity,
            title=title,
            year=1957,
        )
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        titles = resp.json()["titles"]
        assert len(titles) == 1
        assert titles[0]["name"] == "Ace High"

    def test_404_for_unknown_slug(self, client, db):
        resp = client.get("/api/pages/corporate-entity/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH claims — scalars
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchCorporateEntityScalars:
    def test_anonymous_gets_401(self, client, entity):
        resp = _patch(client, entity.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code in (401, 403)

    def test_edit_description(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code == 200
        assert resp.json()["description"]["text"] == "Updated"

    def test_slug_can_be_changed(self, client, user, entity):
        client.force_login(user)
        resp = _patch(
            client,
            entity.slug,
            {"fields": {"slug": "gottlieb-company"}},
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "gottlieb-company"

        entity.refresh_from_db()
        assert entity.slug == "gottlieb-company"
        assert (
            client.get(f"/api/pages/corporate-entity/{entity.slug}").status_code == 200
        )
        assert (
            client.get("/api/pages/corporate-entity/d-gottlieb-company").status_code
            == 404
        )

    def test_duplicate_slug_returns_422(self, client, user, entity, other_entity):
        client.force_login(user)
        resp = _patch(
            client,
            entity.slug,
            {"fields": {"slug": other_entity.slug}},
        )
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()

    def test_edit_years(self, client, user, entity):
        client.force_login(user)
        resp = _patch(
            client, entity.slug, {"fields": {"year_start": 1930, "year_end": 1985}}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["year_start"] == 1930
        assert data["year_end"] == 1985

    def test_edit_operating_status(self, client, user, entity):
        # operating_status is claimable in Commit 1 but not yet exposed in the
        # detail response schema (added in Commit 2), so assert the DB value.
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {"operating_status": "ongoing"}})
        assert resp.status_code == 200
        entity.refresh_from_db()
        assert entity.operating_status == "ongoing"

    def test_invalid_operating_status_returns_422(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {"operating_status": "bogus"}})
        assert resp.status_code == 422
        assert "valid choice" in resp.json()["detail"]["message"].lower()

    def test_no_changes_returns_422(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {}})
        assert resp.status_code == 422

    def test_unknown_field_returns_422(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {"bogus": "value"}})
        assert resp.status_code == 422

    def test_exempt_field_returns_422(self, client, user, entity):
        """manufacturer and ipdb_manufacturer_id are claims-exempt."""
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {"manufacturer": 99}})
        assert resp.status_code == 422

    def test_changeset_with_note(self, client, user, entity):
        client.force_login(user)
        _patch(
            client,
            entity.slug,
            {"fields": {"description": "Updated"}, "note": "Test note"},
        )
        assert ChangeSet.objects.count() == 1
        cs = ChangeSet.objects.first()
        assert cs is not None
        assert cs.note == "Test note"
        assert cs.claims.count() == 1


# ---------------------------------------------------------------------------
# PATCH claims — aliases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchCorporateEntityAliases:
    def test_add_aliases(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"aliases": ["Gottlieb Co", "Gottlieb"]})
        assert resp.status_code == 200
        assert sorted(resp.json()["aliases"]) == ["Gottlieb", "Gottlieb Co"]

    def test_remove_aliases(self, client, user, entity):
        client.force_login(user)
        _patch(client, entity.slug, {"aliases": ["Gottlieb Co"]})
        resp = _patch(client, entity.slug, {"aliases": []})
        assert resp.status_code == 200
        assert resp.json()["aliases"] == []

    def test_display_case_preserved(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"aliases": ["McFarlane"]})
        assert "McFarlane" in resp.json()["aliases"]
        entity.refresh_from_db()
        assert entity.aliases.get().value == "McFarlane"

    def test_null_aliases_leaves_unchanged(self, client, user, entity):
        """aliases: null means 'no change', not 'clear all'."""
        client.force_login(user)
        _patch(client, entity.slug, {"aliases": ["Gottlieb Co"]})
        resp = _patch(
            client, entity.slug, {"fields": {"description": "Updated"}, "aliases": None}
        )
        assert resp.status_code == 200
        assert resp.json()["aliases"] == ["Gottlieb Co"]


# ---------------------------------------------------------------------------
# Edit history endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCorporateEntityEditHistory:
    def test_edit_history_empty(self, client, entity):
        resp = client.get(f"/api/pages/edit-history/corporate-entity/{entity.slug}/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_edit_history_after_edit(self, client, user, entity):
        client.force_login(user)
        _patch(
            client, entity.slug, {"fields": {"description": "Updated"}, "note": "Fix"}
        )
        resp = client.get(f"/api/pages/edit-history/corporate-entity/{entity.slug}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["note"] == "Fix"
        assert any(c["field_name"] == "description" for c in data[0]["changes"])
