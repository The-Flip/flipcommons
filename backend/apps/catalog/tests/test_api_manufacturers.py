from apps.catalog.models import (
    CorporateEntity,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model


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

    def test_get_manufacturer_entities_ordered_by_years(self, client, manufacturer):
        CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Latest",
            slug="williams-latest",
            year_start=1999,
            year_end=2010,
        )
        CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Early",
            slug="williams-mfg",
            year_start=1943,
            year_end=1985,
        )
        CorporateEntity.objects.create(
            manufacturer=manufacturer,
            name="Williams Middle",
            slug="williams-middle",
            year_start=1985,
            year_end=1999,
        )
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
