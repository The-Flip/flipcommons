import pytest
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import System, Title
from apps.catalog.tests.conftest import make_machine_model


class TestStatsAPI:
    def test_stats_returns_correct_counts(self, client, machine_model):
        """Counts must reflect actual rows in the database."""
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        # The machine_model fixture now creates a backing Title (title is
        # NOT NULL on MachineModel).
        assert data["titles"] == 1
        assert data["models"] == 1
        assert data["manufacturers"] == 1
        assert data["people"] == 0

    def test_stats_uses_single_query(self, client, db):
        """The /stats endpoint must fetch all counts in one DB query."""
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            resp = client.get("/api/stats")
        assert resp.status_code == 200
        count_queries = [
            q["sql"] for q in ctx.captured_queries if "COUNT" in q["sql"].upper()
        ]
        assert len(count_queries) == 1, (
            f"Expected 1 count query, got {len(count_queries)}"
        )


class TestSourcesAPI:
    def test_list_sources(self, client, source):
        resp = client.get("/api/sources/")
        assert resp.status_code == 200
        data = resp.json()
        slugs = {s["slug"] for s in data}
        # The IPDB fixture plus the seeded patch-attribution source.
        assert "ipdb" in slugs
        assert "flip-museum" in slugs


class TestSystemsAPI:
    @pytest.fixture
    def system(self, db, manufacturer):
        return System.objects.create(
            name="Williams WPC-95",
            slug="wpc-95",
            manufacturer=manufacturer,
        )

    @pytest.fixture
    def system_with_machines(self, system):
        t1 = Title.objects.create(
            name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4-s"
        )
        t2 = Title.objects.create(
            name="No Good Gofers", slug="no-good-gofers", opdb_id="T-ngg"
        )
        make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            year=1997,
            system=system,
            title=t1,
        )
        make_machine_model(
            name="No Good Gofers",
            slug="no-good-gofers",
            year=1997,
            system=system,
            title=t2,
        )
        return system

    def test_get_system_detail(self, client, system_with_machines):
        resp = client.get("/api/pages/system/wpc-95")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Williams WPC-95"
        assert data["slug"] == "wpc-95"
        assert data["manufacturer"]["name"] == "Williams"
        assert data["technology_subgeneration"] is None
        assert len(data["titles"]) == 2

    def test_get_system_detail_titles_sorted_year_desc(
        self, client, system_with_machines
    ):
        t3 = Title.objects.create(name="Old Title", slug="old-title", opdb_id="T-old-s")
        make_machine_model(
            name="Old Game",
            slug="old-game",
            year=1990,
            system=system_with_machines,
            title=t3,
        )
        resp = client.get("/api/pages/system/wpc-95")
        data = resp.json()
        years = [t["year"] for t in data["titles"] if t["year"]]
        assert years == sorted(years, reverse=True)

    def test_get_system_404(self, client, db):
        resp = client.get("/api/pages/system/nonexistent")
        assert resp.status_code == 404
