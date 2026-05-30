"""Tests for the locations browsing API.

Fixtures use Location + CorporateEntityLocation directly (bypassing claims)
for speed. The URL structure mirrors location_path:
``/api/pages/locations/{path}``. The empty path (``/api/pages/locations/``)
returns the global root view.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    Manufacturer,
)
from apps.catalog.tests.conftest import make_machine_model

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_location(location_path, name, location_type, parent=None, divisions=None):
    slug = location_path.rsplit("/", 1)[-1]
    return Location.objects.create(
        location_path=location_path,
        slug=slug,
        name=name,
        location_type=location_type,
        parent=parent,
        divisions=divisions,
    )


def _make_mfr_at(name, slug, location):
    """Create a Manufacturer + CorporateEntity linked to the given Location."""
    mfr = Manufacturer.objects.create(name=name, slug=slug)
    entity = CorporateEntity.objects.create(name=name, slug=slug, manufacturer=mfr)
    CorporateEntityLocation.objects.create(corporate_entity=entity, location=location)
    return mfr


@pytest.fixture
def locations(db):
    """Standard location tree used across most tests."""
    usa = _make_location("usa", "USA", "country", divisions=["state", "city"])
    il = _make_location("usa/il", "Illinois", "state", parent=usa)
    chicago = _make_location("usa/il/chicago", "Chicago", "city", parent=il)
    egv = _make_location(
        "usa/il/elk-grove-village", "Elk Grove Village", "city", parent=il
    )
    nl = _make_location("netherlands", "Netherlands", "country")
    reuver = _make_location("netherlands/reuver", "Reuver", "city", parent=nl)
    return {
        "usa": usa,
        "il": il,
        "chicago": chicago,
        "egv": egv,
        "netherlands": nl,
        "reuver": reuver,
    }


@pytest.fixture
def manufacturers(db, locations):
    """Standard manufacturers linked to the location tree."""
    williams = _make_mfr_at("Williams", "williams-electronics", locations["chicago"])
    gottlieb = _make_mfr_at("Gottlieb", "d-gottlieb-co", locations["chicago"])
    stern = _make_mfr_at("Stern", "stern-pinball-inc", locations["egv"])
    dutch = _make_mfr_at("Dutch Pinball", "dutch-pinball", locations["reuver"])
    return {"williams": williams, "gottlieb": gottlieb, "stern": stern, "dutch": dutch}


# ---------------------------------------------------------------------------
# Root (global) view
# ---------------------------------------------------------------------------


class TestLocationsRoot:
    def test_returns_detail_shape(self, client, manufacturers):
        resp = client.get("/api/pages/locations/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == ""
        assert data["slug"] == ""
        assert data["public_id"] == ""
        assert data["location_type"] is None
        assert data["ancestors"] == []

    def test_children_are_countries(self, client, manufacturers):
        resp = client.get("/api/pages/locations/")
        names = {c["name"] for c in resp.json()["children"]}
        assert "USA" in names
        assert "Netherlands" in names

    def test_country_has_manufacturer_count(self, client, manufacturers):
        resp = client.get("/api/pages/locations/")
        usa = next(c for c in resp.json()["children"] if c["public_id"] == "usa")
        assert usa["manufacturer_count"] == 3

    def test_global_manufacturer_count_is_union(self, client, manufacturers):
        resp = client.get("/api/pages/locations/")
        # 3 in USA + 1 in Netherlands = 4 distinct manufacturers worldwide
        assert resp.json()["manufacturer_count"] == 4

    def test_global_manufacturers_payload(self, client, manufacturers):
        resp = client.get("/api/pages/locations/")
        names = {m["name"] for m in resp.json()["manufacturers"]}
        assert names == {"Williams", "Gottlieb", "Stern", "Dutch Pinball"}


# ---------------------------------------------------------------------------
# Generic location detail (any depth)
# ---------------------------------------------------------------------------


class TestCountryDetail:
    def test_returns_country(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "USA"
        assert data["location_type"] == "country"
        assert data["manufacturer_count"] == 3

    def test_includes_manufacturers(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa")
        mfr_names = {m["name"] for m in resp.json()["manufacturers"]}
        assert mfr_names == {"Williams", "Gottlieb", "Stern"}

    def test_includes_children(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa")
        child_names = {c["name"] for c in resp.json()["children"]}
        assert "Illinois" in child_names

    def test_404_for_unknown(self, client, db):
        assert client.get("/api/pages/locations/atlantis").status_code == 404


class TestSubdivisionDetail:
    def test_returns_state(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa/il")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Illinois"
        assert data["location_type"] == "state"
        assert data["manufacturer_count"] == 3

    def test_includes_ancestor_chain(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa/il")
        data = resp.json()
        # Ancestors should include USA
        ancestor_names = {a["name"] for a in data["ancestors"]}
        assert "USA" in ancestor_names

    def test_includes_cities(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa/il")
        child_names = {c["name"] for c in resp.json()["children"]}
        assert "Chicago" in child_names
        assert "Elk Grove Village" in child_names

    def test_cities_sorted_by_manufacturer_count_then_name(self, client, db, locations):
        # Zephyr has two manufacturers, Albany has one → Zephyr first
        zephyr = _make_location(
            "usa/il/zephyr", "Zephyr", "city", parent=locations["il"]
        )
        albany = _make_location(
            "usa/il/albany", "Albany", "city", parent=locations["il"]
        )
        _make_mfr_at("Alpha", "alpha", zephyr)
        _make_mfr_at("Beta", "beta", zephyr)
        _make_mfr_at("Gamma", "gamma", albany)

        resp = client.get("/api/pages/locations/usa/il")
        child_names = [c["name"] for c in resp.json()["children"]]
        assert child_names.index("Zephyr") < child_names.index("Albany")

    def test_404_for_unknown(self, client, manufacturers):
        assert client.get("/api/pages/locations/usa/tx").status_code == 404


class TestCityDetail:
    def test_returns_city_with_state(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa/il/chicago")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Chicago"
        assert data["location_type"] == "city"
        assert data["manufacturer_count"] == 2

    def test_includes_ancestor_chain(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa/il/chicago")
        ancestor_names = {a["name"] for a in resp.json()["ancestors"]}
        assert "USA" in ancestor_names
        assert "Illinois" in ancestor_names

    def test_city_includes_correct_manufacturers(self, client, manufacturers):
        resp = client.get("/api/pages/locations/usa/il/chicago")
        mfr_names = {m["name"] for m in resp.json()["manufacturers"]}
        assert mfr_names == {"Williams", "Gottlieb"}

    def test_404_for_unknown_city(self, client, manufacturers):
        assert client.get("/api/pages/locations/usa/il/springfield").status_code == 404

    def test_city_directly_under_country(self, client, manufacturers):
        """City with no subdivision (Netherlands → Reuver)."""
        resp = client.get("/api/pages/locations/netherlands/reuver")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Reuver"
        assert data["location_type"] == "city"
        assert data["manufacturer_count"] == 1
        ancestor_names = {a["name"] for a in data["ancestors"]}
        assert "Netherlands" in ancestor_names


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class TestLocationsCacheInvalidation:
    def test_index_refreshes_when_location_added(self, client, db, locations):
        _make_mfr_at("Williams", "williams", locations["chicago"])

        initial = client.get("/api/pages/locations/")
        usa = next(c for c in initial.json()["children"] if c["public_id"] == "usa")
        assert usa["manufacturer_count"] == 1

        # Add another manufacturer to a new city — cache should invalidate
        new_city = _make_location(
            "usa/il/rockford", "Rockford", "city", parent=locations["il"]
        )
        _make_mfr_at("Bally", "bally", new_city)

        refreshed = client.get("/api/pages/locations/")
        usa_refreshed = next(
            c for c in refreshed.json()["children"] if c["public_id"] == "usa"
        )
        assert usa_refreshed["manufacturer_count"] == 2

    def test_index_refreshes_when_location_name_changes(self, client, db, locations):
        _make_mfr_at("Williams", "williams", locations["chicago"])
        initial = client.get("/api/pages/locations/")
        usa = next(c for c in initial.json()["children"] if c["public_id"] == "usa")
        assert usa["name"] == "USA"

        # Rename the country — cache should invalidate
        locations["usa"].name = "United States"
        locations["usa"].save()

        refreshed = client.get("/api/pages/locations/")
        usa_refreshed = next(
            c for c in refreshed.json()["children"] if c["public_id"] == "usa"
        )
        assert usa_refreshed["name"] == "United States"


# ---------------------------------------------------------------------------
# expected_child_type — frontend-facing label for the "+ New ..." action.
# Cache-derived from the country ancestor's ``divisions`` list, so a
# regression in ``_LocationNode.divisions`` population or in
# ``lookup_child_division`` would silently degrade the API. These five
# cases pin the contract.
# ---------------------------------------------------------------------------


class TestExpectedChildType:
    def test_root_returns_country(self, client, locations):
        resp = client.get("/api/pages/locations/")
        assert resp.json()["expected_child_type"] == "country"

    def test_country_returns_first_division(self, client, locations):
        # USA carries divisions=["state", "city"]; depth 0 -> "state"
        resp = client.get("/api/pages/locations/usa")
        assert resp.json()["expected_child_type"] == "state"

    def test_subdivision_returns_next_division(self, client, locations):
        # state under USA -> depth 1 -> "city"
        resp = client.get("/api/pages/locations/usa/il")
        assert resp.json()["expected_child_type"] == "city"

    def test_exhausted_divisions_returns_null(self, client, locations):
        # Chicago is at depth 2; USA only declares 2 division levels,
        # so a level-3 child has no derivable type.
        resp = client.get("/api/pages/locations/usa/il/chicago")
        assert resp.json()["expected_child_type"] is None

    def test_missing_divisions_returns_null(self, client, locations):
        # Netherlands has no divisions declared (None).
        resp = client.get("/api/pages/locations/netherlands")
        assert resp.json()["expected_child_type"] is None
        # And any child of a no-divisions country also resolves to null.
        resp = client.get("/api/pages/locations/netherlands/reuver")
        assert resp.json()["expected_child_type"] is None


# ---------------------------------------------------------------------------
# Query-count regression: the manufacturers payload uses a nested
# ``Prefetch("models", queryset=...only(...))``. If the FK back-pointer
# (``corporate_entity_id``) is omitted from ``.only(...)``, Django's
# prefetch machinery refresh_from_db's it per row, scaling queries
# linearly with the MachineModel count in the response.
# ---------------------------------------------------------------------------


class TestManufacturersQueryCount:
    def _add_models(self, mfr, count, slug_prefix):
        """Attach ``count`` MachineModels to the manufacturer's CorporateEntity."""
        entity = mfr.entities.get()
        for i in range(count):
            make_machine_model(
                name=f"{slug_prefix}-{i}",
                slug=f"{slug_prefix}-{i}",
                corporate_entity=entity,
            )

    def test_query_count_does_not_scale_with_machine_models(
        self, client, manufacturers
    ):
        # Baseline: one MachineModel per relevant manufacturer.
        self._add_models(manufacturers["williams"], 1, "williams-mm")
        self._add_models(manufacturers["gottlieb"], 1, "gottlieb-mm")
        self._add_models(manufacturers["stern"], 1, "stern-mm")

        # Warm caches at the small-N dataset, then measure on warm cache.
        client.get("/api/pages/locations/usa")
        with CaptureQueriesContext(connection) as small_ctx:
            resp = client.get("/api/pages/locations/usa")
            assert resp.status_code == 200
        small_count = len(small_ctx.captured_queries)

        # Add many more MachineModels under the same manufacturers.
        # This invalidates the location tree cache, so warm it again
        # before measuring so both measurements pay the same warm-cache cost.
        self._add_models(manufacturers["williams"], 9, "williams-extra")
        self._add_models(manufacturers["gottlieb"], 9, "gottlieb-extra")
        self._add_models(manufacturers["stern"], 9, "stern-extra")

        client.get("/api/pages/locations/usa")
        with CaptureQueriesContext(connection) as big_ctx:
            resp = client.get("/api/pages/locations/usa")
            assert resp.status_code == 200
        big_count = len(big_ctx.captured_queries)

        assert big_count == small_count, (
            f"Query count scaled with MachineModel count: {small_count} at N=3, "
            f"{big_count} at N=30. Likely a refresh_from_db-per-row caused "
            f"by a Prefetch().only(...) omitting the FK back-pointer.\n"
            f"Extra queries:\n"
            + "\n".join(q["sql"] for q in big_ctx.captured_queries[small_count:])
        )
