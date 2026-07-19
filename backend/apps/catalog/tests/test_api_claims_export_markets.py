"""Tests for export-edition and export-market editing via
PATCH /api/models/{public_id}/claims/ — the Exports.md feature surface."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Location, MachineModel, ModelExportMarket
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.test_factories import make_claim

User = get_user_model()


@pytest.fixture
def pm(db, bootstrap_source):
    pm = make_machine_model(name="Black Magic", slug="black-magic", year=1980)
    make_claim(pm, "name", "Black Magic", ingest_source=bootstrap_source)
    return pm


@pytest.fixture
def domestic(db):
    return make_machine_model(name="Black Magic 4", slug="black-magic-4", year=1980)


def _country(path: str, name: str) -> Location:
    return Location.objects.create(
        location_path=path, slug=path, name=name, location_type="country"
    )


@pytest.fixture
def italy(db) -> Location:
    return _country("italy", "Italy")


@pytest.fixture
def france(db) -> Location:
    return _country("france", "France")


def _patch(client, slug, body):
    return client.patch(
        f"/api/models/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _market_rows(pm: MachineModel) -> set[tuple[str | None, str]]:
    return {
        (
            m.target_market_location.location_path
            if m.target_market_location
            else None,
            m.target_market_label,
        )
        for m in ModelExportMarket.objects.filter(machine_model=pm)
    }


# ---------------------------------------------------------------------------
# export_edition_of — the scalar lineage FK
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportEditionOf:
    def test_set_and_serialize(self, client, user, pm, domestic):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"export_edition_of": domestic.slug}})
        assert resp.status_code == 200
        assert resp.json()["export_edition_of"]["public_id"] == domestic.slug

        pm.refresh_from_db()
        assert pm.export_edition_of_id == domestic.pk

    def test_reverse_list_serializes(self, client, user, pm, domestic):
        client.force_login(user)
        _patch(client, pm.slug, {"fields": {"export_edition_of": domestic.slug}})
        resp = client.get(f"/api/pages/model/{domestic.slug}")
        assert resp.status_code == 200
        detail = resp.json()
        assert [m["public_id"] for m in detail["export_editions"]] == [pm.slug]

    def test_clear(self, client, user, pm, domestic):
        client.force_login(user)
        _patch(client, pm.slug, {"fields": {"export_edition_of": domestic.slug}})
        resp = _patch(client, pm.slug, {"fields": {"export_edition_of": None}})
        assert resp.status_code == 200
        pm.refresh_from_db()
        assert pm.export_edition_of_id is None

    def test_self_reference_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"fields": {"export_edition_of": pm.slug}})
        assert resp.status_code == 422
        assert "itself" in json.dumps(resp.json())


# ---------------------------------------------------------------------------
# export_markets — the desired-list planner
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportMarkets:
    def test_add_country_rows(self, client, user, pm, italy, france):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "export_markets": [
                    {"target_location": "italy"},
                    {"target_location": "france"},
                ]
            },
        )
        assert resp.status_code == 200
        assert _market_rows(pm) == {("italy", ""), ("france", "")}
        markets = resp.json()["export_markets"]
        assert sorted(m["target_location"]["public_id"] for m in markets) == [
            "france",
            "italy",
        ]

    def test_add_label_row(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"export_markets": [{"target_label": "Europe"}]})
        assert resp.status_code == 200
        assert _market_rows(pm) == {(None, "Europe")}
        assert resp.json()["export_markets"] == [
            {"target_location": None, "target_label": "Europe"}
        ]

    def test_add_unknown_row(self, client, user, pm):
        client.force_login(user)
        resp = _patch(client, pm.slug, {"export_markets": [{}]})
        assert resp.status_code == 200
        assert _market_rows(pm) == {(None, "")}

    def test_remove_rows(self, client, user, pm, italy):
        client.force_login(user)
        _patch(client, pm.slug, {"export_markets": [{"target_location": "italy"}]})
        resp = _patch(client, pm.slug, {"export_markets": []})
        assert resp.status_code == 200
        assert _market_rows(pm) == set()

    def test_label_reword_supersedes_in_place(self, client, user, pm):
        client.force_login(user)
        _patch(client, pm.slug, {"export_markets": [{"target_label": "Europe"}]})
        original_pk = ModelExportMarket.objects.get(machine_model=pm).pk
        resp = _patch(
            client, pm.slug, {"export_markets": [{"target_label": "Western Europe"}]}
        )
        assert resp.status_code == 200
        row = ModelExportMarket.objects.get(machine_model=pm)
        assert row.pk == original_pk
        assert row.target_market_label == "Western Europe"

    def test_unchanged_rows_are_noop(self, client, user, pm, italy):
        client.force_login(user)
        _patch(client, pm.slug, {"export_markets": [{"target_location": "italy"}]})
        # Re-sending the same list alone plans no claims → "No changes".
        resp = _patch(
            client, pm.slug, {"export_markets": [{"target_location": "italy"}]}
        )
        assert resp.status_code == 422
        assert "No changes" in json.dumps(resp.json())

    def test_both_targets_rejected(self, client, user, pm, italy):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "export_markets": [
                    {"target_location": "italy", "target_label": "Europe"}
                ]
            },
        )
        assert resp.status_code == 422

    def test_non_country_location_rejected(self, client, user, pm, italy):
        Location.objects.create(
            location_path="italy/rome", slug="rome", name="Rome", parent=italy
        )
        client.force_login(user)
        resp = _patch(
            client, pm.slug, {"export_markets": [{"target_location": "italy/rome"}]}
        )
        assert resp.status_code == 422
        assert "country" in json.dumps(resp.json())

    def test_duplicate_country_rejected(self, client, user, pm, italy):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "export_markets": [
                    {"target_location": "italy"},
                    {"target_location": "italy"},
                ]
            },
        )
        assert resp.status_code == 422

    def test_two_null_location_rows_rejected(self, client, user, pm):
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {"export_markets": [{"target_label": "Europe"}, {}]},
        )
        assert resp.status_code == 422

    def test_null_location_row_must_be_only_row(self, client, user, pm, italy):
        # The Exports.md shape rule: a label or unknown row cannot be combined
        # with country rows.
        client.force_login(user)
        resp = _patch(
            client,
            pm.slug,
            {
                "export_markets": [
                    {"target_location": "italy"},
                    {"target_label": "Europe"},
                ]
            },
        )
        assert resp.status_code == 422

    def test_null_leaves_unchanged(self, client, user, pm, italy):
        client.force_login(user)
        _patch(client, pm.slug, {"export_markets": [{"target_location": "italy"}]})
        resp = _patch(client, pm.slug, {"fields": {"year": 1981}})
        assert resp.status_code == 200
        assert _market_rows(pm) == {("italy", "")}


# ---------------------------------------------------------------------------
# edit-options — the country picker's option list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_edit_options_lists_countries_only(client, italy):
    Location.objects.create(
        location_path="italy/rome", slug="rome", name="Rome", parent=italy
    )
    resp = client.get("/api/models/edit-options/")
    assert resp.status_code == 200
    countries = resp.json()["countries"]
    assert {"slug": "italy", "label": "Italy"} in countries
    assert all(c["slug"] != "italy/rome" for c in countries)
