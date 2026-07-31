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
from apps.provenance.models import ChangeSet
from apps.provenance.test_factories import make_claim

User = get_user_model()


@pytest.fixture
def mfr(db, bootstrap_source):
    m = Manufacturer.objects.create(name="Gottlieb", slug="gottlieb")
    make_claim(m, "name", "Gottlieb", ingest_source=bootstrap_source)
    return m


@pytest.fixture
def entity(db, mfr, bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="D. Gottlieb & Company",
        slug="d-gottlieb-company",
        manufacturer=mfr,
        year_start=1927,
        year_end=1983,
    )
    make_claim(ce, "name", "D. Gottlieb & Company", ingest_source=bootstrap_source)
    return ce


@pytest.fixture
def other_entity(db, mfr, bootstrap_source):
    ce = CorporateEntity.objects.create(
        name="Mylstar Electronics",
        slug="mylstar-electronics",
        manufacturer=mfr,
        year_start=1983,
        year_end=1984,
    )
    make_claim(ce, "name", "Mylstar Electronics", ingest_source=bootstrap_source)
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

    def test_list_includes_production_span(self, client, entity):
        make_machine_model(
            name="Early", slug="early", corporate_entity=entity, year=1960
        )
        make_machine_model(name="Late", slug="late", corporate_entity=entity, year=1975)
        resp = client.get("/api/corporate-entities/")
        row = next(r for r in resp.json()["items"] if r["slug"] == entity.slug)
        assert row["year_of_first_model"] == 1960
        assert row["year_of_last_model"] == 1975
        assert row["operating_status"] == "unknown"

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

    def test_detail_embeds_games(self, client, entity):
        title = Title.objects.create(name="Ace High", slug="ace-high")
        make_machine_model(
            name="Ace High",
            slug="ace-high",
            corporate_entity=entity,
            title=title,
            year=1957,
        )
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        games = resp.json()["games"]
        assert games["count"] == 1
        assert games["items"][0]["name"] == "Ace High"

    def test_detail_production_span(self, client, entity):
        make_machine_model(
            name="Early", slug="early", corporate_entity=entity, year=1960
        )
        make_machine_model(name="Late", slug="late", corporate_entity=entity, year=1975)
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        data = resp.json()
        assert data["year_of_first_model"] == 1960
        assert data["year_of_last_model"] == 1975
        # No operating_status claim → resolved column default "unknown".
        assert data["operating_status"] == "unknown"

    def test_detail_production_span_null_when_no_years(self, client, entity):
        make_machine_model(name="Undated", slug="undated", corporate_entity=entity)
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        data = resp.json()
        assert data["year_of_first_model"] is None
        assert data["year_of_last_model"] is None

    def test_detail_operating_status(self, client, entity):
        entity.operating_status = "ongoing"
        entity.save()
        resp = client.get(f"/api/pages/corporate-entity/{entity.slug}")
        assert resp.json()["operating_status"] == "ongoing"

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
        # year_start/year_end remain claimable (DB columns + claims are kept) even
        # though they're no longer surfaced in the read response, so assert the
        # resolved DB values rather than the response body.
        client.force_login(user)
        resp = _patch(
            client, entity.slug, {"fields": {"year_start": 1930, "year_end": 1985}}
        )
        assert resp.status_code == 200
        entity.refresh_from_db()
        assert entity.year_start == 1930
        assert entity.year_end == 1985

    def test_edit_operating_status(self, client, user, entity):
        client.force_login(user)
        resp = _patch(client, entity.slug, {"fields": {"operating_status": "ongoing"}})
        assert resp.status_code == 200
        assert resp.json()["operating_status"] == "ongoing"

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
        # Fixtures assert seed (ingest) name claims, so filter to the user's
        # changeset rather than assuming it's the only row.
        assert ChangeSet.objects.filter(actor=user.actor).count() == 1
        cs = ChangeSet.objects.get(actor=user.actor)
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
        # Seed name claims surface as ingest changesets; only user edits count here.
        user_entries = [
            cs for cs in resp.json() if cs["attribution"]["author"]["kind"] == "user"
        ]
        assert user_entries == []

    def test_edit_history_after_edit(self, client, user, entity):
        client.force_login(user)
        _patch(
            client, entity.slug, {"fields": {"description": "Updated"}, "note": "Fix"}
        )
        resp = client.get(f"/api/pages/edit-history/corporate-entity/{entity.slug}/")
        assert resp.status_code == 200
        # Filter out fixture seed (ingest) changesets; assert only the user edit.
        user_entries = [
            cs for cs in resp.json() if cs["attribution"]["author"]["kind"] == "user"
        ]
        assert len(user_entries) == 1
        assert user_entries[0]["note"] == "Fix"
        assert any(c["field_name"] == "description" for c in user_entries[0]["changes"])
