from apps.catalog.models import (
    CorporateEntity,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.test_factories import make_claim


class TestManufacturersAPI:
    def test_list_manufacturers(self, client, manufacturer, machine_model):
        resp = client.get("/api/manufacturers/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "Williams"
        assert data["items"][0]["model_count"] == 1

    def test_get_manufacturer_detail(
        self, client, manufacturer, williams_entity, machine_model
    ):
        title = Title.objects.create(
            name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4"
        )
        machine_model.title = title
        machine_model.save()
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Williams"
        assert len(data["entities"]) == 1
        assert data["entities"][0]["name"] == "Williams Electronics"
        assert len(data["titles"]) == 1
        assert data["titles"][0]["name"] == "Medieval Madness"

    def test_get_manufacturer_detail_external_ids(self, client, manufacturer):
        manufacturer.opdb_manufacturer_id = 42
        manufacturer.wikidata_id = "Q12345"
        manufacturer.save()
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["opdb_manufacturer_id"] == 42
        assert data["wikidata_id"] == "Q12345"

    def test_get_manufacturer_entities_ordered_by_first_model_year(
        self, client, manufacturer
    ):
        """Companies sort by when they began producing (earliest model year)."""
        latest = CorporateEntity.objects.create(
            manufacturer=manufacturer, name="Williams Latest", slug="williams-latest"
        )
        early = CorporateEntity.objects.create(
            manufacturer=manufacturer, name="Williams Early", slug="williams-mfg"
        )
        middle = CorporateEntity.objects.create(
            manufacturer=manufacturer, name="Williams Middle", slug="williams-middle"
        )
        make_machine_model(name="L", slug="l", corporate_entity=latest, year=1999)
        make_machine_model(name="E", slug="e", corporate_entity=early, year=1943)
        make_machine_model(name="M", slug="m", corporate_entity=middle, year=1985)
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        entities = resp.json()["entities"]
        assert [e["name"] for e in entities] == [
            "Williams Early",
            "Williams Middle",
            "Williams Latest",
        ]

    def test_get_manufacturer_detail_titles_sorted_year_desc(
        self, client, manufacturer, williams_entity, db
    ):
        """Titles should be sorted newest-first, even across multiple entities."""
        entity2 = CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Early",
            slug="williams-early",
            year_start=1943,
            year_end=1985,
        )
        t_old = Title.objects.create(name="Old Game", slug="old-game", opdb_id="T-old")
        t_mid = Title.objects.create(name="Mid Game", slug="mid-game", opdb_id="T-mid")
        t_new = Title.objects.create(name="New Game", slug="new-game", opdb_id="T-new")
        make_machine_model(
            name="Old", slug="old", corporate_entity=entity2, title=t_old, year=1960
        )
        make_machine_model(
            name="Mid",
            slug="mid",
            corporate_entity=williams_entity,
            title=t_mid,
            year=1995,
        )
        make_machine_model(
            name="New",
            slug="new",
            corporate_entity=williams_entity,
            title=t_new,
            year=2020,
        )
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        years = [t["year"] for t in resp.json()["titles"]]
        assert years == [2020, 1995, 1960]

    def test_get_manufacturer_detail_nulls_last(
        self, client, manufacturer, williams_entity, db
    ):
        t1 = Title.objects.create(
            name="No Year Title", slug="no-year-title", opdb_id="T-noyear"
        )
        t2 = Title.objects.create(
            name="Has Year Title", slug="has-year-title", opdb_id="T-hasyear"
        )
        make_machine_model(
            name="No Year Game",
            slug="no-year-game",
            corporate_entity=williams_entity,
            title=t1,
        )
        make_machine_model(
            name="Has Year Game",
            slug="has-year-game",
            corporate_entity=williams_entity,
            year=2020,
            title=t2,
        )
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        data = resp.json()
        names = [t["name"] for t in data["titles"]]
        assert names[-1] == "No Year Title"

    def test_get_manufacturer_production_span(
        self, client, manufacturer, williams_entity
    ):
        make_machine_model(
            name="Early", slug="early", corporate_entity=williams_entity, year=1985
        )
        make_machine_model(
            name="Late", slug="late", corporate_entity=williams_entity, year=2003
        )
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        data = resp.json()
        # Top-level production span across all entities' models.
        assert data["year_of_first_model"] == 1985
        assert data["year_of_last_model"] == 2003
        # No operating_status claim anywhere → defaults to "unknown".
        assert data["operating_status"] == "unknown"
        # Same fields mirrored on each nested corporate entity.
        entity = data["entities"][0]
        assert entity["year_of_first_model"] == 1985
        assert entity["year_of_last_model"] == 2003
        assert entity["operating_status"] == "unknown"

    def test_manufacturer_operating_status_rolls_up(
        self, client, manufacturer, williams_entity, source
    ):
        from apps.catalog.resolve import resolve_entity

        make_claim(williams_entity, "operating_status", "ongoing", ingest_source=source)
        resolve_entity(williams_entity)
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        data = resp.json()
        assert data["operating_status"] == "ongoing"
        assert data["entities"][0]["operating_status"] == "ongoing"

    def test_manufacturer_production_span_null_when_no_years(
        self, client, manufacturer, williams_entity
    ):
        # A manufacturer whose only model lacks a year → null bounds, no crash.
        make_machine_model(
            name="Undated", slug="undated", corporate_entity=williams_entity
        )
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        data = resp.json()
        assert data["year_of_first_model"] is None
        assert data["year_of_last_model"] is None
        assert data["entities"][0]["year_of_first_model"] is None

    def test_manufacturer_with_no_entities(self, client, manufacturer):
        # No corporate entities at all → empty span, unknown status (not ended).
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        data = resp.json()
        assert data["entities"] == []
        assert data["year_of_first_model"] is None
        assert data["year_of_last_model"] is None
        assert data["operating_status"] == "unknown"
