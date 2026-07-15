import pytest
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import (
    Credit,
    CreditRole,
    LicenseStatus,
    MachineModel,
    ModelAbbreviation,
    ModelRelationship,
    RelationshipType,
    Title,
    TitleAbbreviation,
)
from apps.catalog.resolve import resolve_relationship
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.claims import build_relationship_claim
from apps.provenance.test_factories import make_claim, make_ingest_source

from .conftest import SAMPLE_IMAGES


class TestModelsAPI:
    def test_list_models(self, client, machine_model):
        resp = client.get("/api/models/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "Medieval Madness"

    def test_list_models_filter_manufacturer(
        self, client, machine_model, another_model
    ):
        resp = client.get("/api/models/?manufacturer=williams")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "Medieval Madness"

    def test_list_models_filter_type(self, client, machine_model):
        resp = client.get("/api/models/?type=solid-state")
        data = resp.json()
        assert data["count"] == 1

        resp = client.get("/api/models/?type=electromechanical")
        data = resp.json()
        assert data["count"] == 0

    def test_list_models_filter_year_range(self, client, machine_model, another_model):
        resp = client.get("/api/models/?year_min=2000&year_max=2025")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "The Mandalorian"

    def test_list_models_filter_person(
        self, client, machine_model, person, credit_roles
    ):
        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(model=machine_model, person=person, role=role)
        resp = client.get("/api/models/?person=pat-lawlor")
        data = resp.json()
        assert data["count"] == 1

    def test_list_models_filter_tag(self, client, machine_model, another_model):
        from apps.catalog.models import MachineModelTag, Tag

        widebody = Tag.objects.create(name="Widebody", slug="widebody")
        MachineModelTag.objects.create(machinemodel=machine_model, tag=widebody)
        data = client.get("/api/models/?tag=widebody").json()
        assert data["count"] == 1
        assert [item["slug"] for item in data["items"]] == [machine_model.slug]

    def test_conversion_edge_readmits_variant(self, client, machine_model):
        # The variant collapse re-admits conversions; an edge-based conversion
        # (no legacy converted_from FK) must be re-admitted the same way.
        retheme = make_machine_model(
            name="Retheme", slug="retheme", title=machine_model.title, year=1998
        )
        retheme.variant_of = machine_model
        retheme.save(update_fields=["variant_of"])
        assert client.get("/api/models/").json()["count"] == 1

        ModelRelationship.objects.create(
            machine_model=retheme,
            target_machine=machine_model,
            relationship_type=RelationshipType.CONVERSION,
        )
        names = {m["name"] for m in client.get("/api/models/").json()["items"]}
        assert names == {"Medieval Madness", "Retheme"}

    def test_list_models_ordering(self, client, machine_model, another_model):
        resp = client.get("/api/models/?ordering=-year")
        data = resp.json()
        assert data["items"][0]["name"] == "The Mandalorian"

    def test_list_models_ordering_nulls_last(self, client, machine_model, db):
        """Models with no year sort after models with a year."""
        make_machine_model(name="Unknown Year Game", slug="unknown-year-game")
        resp = client.get("/api/models/?ordering=-year")
        data = resp.json()
        names = [m["name"] for m in data["items"]]
        assert names[-1] == "Unknown Year Game"

    def test_list_models_ordering_stable(self, client, db):
        """Models with the same year are sorted by name for stability."""
        make_machine_model(name="Zeta", slug="zeta", year=2000)
        make_machine_model(name="Alpha", slug="alpha", year=2000)
        resp = client.get("/api/models/?ordering=-year")
        data = resp.json()
        names = [m["name"] for m in data["items"]]
        assert names == ["Alpha", "Zeta"]

    def test_list_models_excludes_variants(self, client, machine_model):
        make_machine_model(
            name="Medieval Madness (LE)",
            slug="medieval-madness-le",
            variant_of=machine_model,
        )
        resp = client.get("/api/models/")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "Medieval Madness"

    def test_list_models_thumbnail(self, client, db):
        make_machine_model(
            name="With Image",
            slug="with-image",
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        resp = client.get("/api/models/")
        data = resp.json()
        assert data["items"][0]["thumbnail_url"] == "https://img.opdb.org/md.jpg"

    def test_get_model_detail(
        self, client, machine_model, person, source, credit_roles
    ):
        role = CreditRole.objects.get(slug="design")
        Credit.objects.create(model=machine_model, person=person, role=role)
        make_claim(machine_model, "year", 1997, ingest_source=source)

        resp = client.get(f"/api/pages/model/{machine_model.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Medieval Madness"
        assert len(data["credits"]) == 1
        assert data["credits"][0]["person"]["name"] == "Pat Lawlor"

        sources_resp = client.get(f"/api/pages/sources/model/{machine_model.slug}/")
        assert sources_resp.status_code == 200
        year_claims = [
            c for c in sources_resp.json()["sources"] if c["field_name"] == "year"
        ]
        assert len(year_claims) == 1
        assert year_claims[0]["attribution"]["author"] == {
            "kind": "source",
            "name": "IPDB",
        }
        assert year_claims[0]["is_winner"] is True

    def test_lineage_refs_carry_manufacturer(self, client, machine_model, stern_entity):
        # A same-named lineage link (a copy keeps the original's name) reads as
        # a relation to itself unless the ref carries a maker. Variants carry
        # one too, so a different-maker variant disambiguates like any other
        # lineage link rather than being the one that can't. (Edge refs are
        # covered by test_relationship_edge_serialized_both_directions.)
        make_machine_model(
            name="Medieval Madness (bootleg edition)",
            slug="medieval-madness-variant",
            corporate_entity=stern_entity,
            variant_of=machine_model,
        )
        original = client.get(f"/api/pages/model/{machine_model.slug}").json()
        assert original["variants"][0]["manufacturer"]["name"] == "Stern"

    def test_relationship_edge_serialized_both_directions(
        self, client, machine_model, stern_entity
    ):
        # One edge appears outbound on the subject (`relationships`) and
        # inbound on the target (`inbound_relationships`), each side carrying
        # a maker-bearing ref like the legacy lineage links.
        copy = make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness-copy",
            corporate_entity=stern_entity,
        )
        ModelRelationship.objects.create(
            machine_model=copy,
            target_machine=machine_model,
            relationship_type=RelationshipType.COPY,
            license_status=LicenseStatus.UNLICENSED,
        )

        outbound = client.get(f"/api/pages/model/{copy.slug}").json()
        (edge,) = outbound["relationships"]
        assert edge["relationship_type"] == "copy"
        assert edge["license_status"] == "unlicensed"
        assert edge["target_machine"]["public_id"] == machine_model.slug
        assert edge["target_machine"]["manufacturer"]["name"] == "Williams"
        assert outbound["inbound_relationships"] == []

        inbound = client.get(f"/api/pages/model/{machine_model.slug}").json()
        (edge,) = inbound["inbound_relationships"]
        assert edge["relationship_type"] == "copy"
        assert edge["license_status"] == "unlicensed"
        assert edge["source_machine"]["public_id"] == copy.slug
        assert edge["source_machine"]["manufacturer"]["name"] == "Stern"

    def test_label_target_edge_serializes_outbound_only(self, client, machine_model):
        ModelRelationship.objects.create(
            machine_model=machine_model,
            target_label="several Gottlieb EM models",
            relationship_type=RelationshipType.CONVERSION_KIT,
        )
        data = client.get(f"/api/pages/model/{machine_model.slug}").json()
        (edge,) = data["relationships"]
        assert edge["target_machine"] is None
        assert edge["target_label"] == "several Gottlieb EM models"

    def test_get_model_detail_images(self, client, db):
        pm = make_machine_model(
            name="With Image",
            slug="with-image",
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        resp = client.get(f"/api/pages/model/{pm.slug}")
        data = resp.json()
        assert data["thumbnail_url"] == "https://img.opdb.org/md.jpg"
        assert data["hero_image_url"] == "https://img.opdb.org/lg.jpg"

    def test_get_model_detail_no_images(self, client, machine_model):
        resp = client.get(f"/api/pages/model/{machine_model.slug}")
        data = resp.json()
        assert data["thumbnail_url"] is None
        assert data["hero_image_url"] is None

    def test_get_model_detail_variant_features(self, client, db):
        pm = make_machine_model(
            name="With Features",
            slug="with-features",
            extra_data={"opdb.variant_features": ["Castle attack", "Gold trim"]},
        )
        resp = client.get(f"/api/pages/model/{pm.slug}")
        data = resp.json()
        assert data["variant_features"] == ["Castle attack", "Gold trim"]

    def test_get_model_detail_variants(self, client, machine_model):
        make_machine_model(
            name="Medieval Madness (LE)",
            slug="medieval-madness-le",
            variant_of=machine_model,
            extra_data={"opdb.variant_features": ["Gold trim"]},
        )
        resp = client.get(f"/api/pages/model/{machine_model.slug}")
        data = resp.json()
        assert len(data["variants"]) == 1
        assert data["variants"][0]["name"] == "Medieval Madness (LE)"
        assert data["variants"][0]["variant_features"] == ["Gold trim"]

    def test_get_model_detail_title(self, client, machine_model, db):
        title = Title.objects.create(
            name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4"
        )
        machine_model.title = title
        machine_model.save()
        resp = client.get(f"/api/pages/model/{machine_model.slug}")
        data = resp.json()
        assert data["title"]["name"] == "Medieval Madness"
        assert data["title"]["public_id"] == title.public_id

    def test_conversions_appear_in_list(self, client, db):
        """Conversions are NOT filtered from the list endpoint (unlike variants)."""
        source = make_machine_model(name="Star Trek", slug="star-trek", year=1991)
        make_machine_model(
            name="Dark Rider",
            slug="dark-rider",
            converted_from=source,
        )
        resp = client.get("/api/models/")
        data = resp.json()
        names = [m["name"] for m in data["items"]]
        assert "Dark Rider" in names
        assert "Star Trek" in names

    def test_conversion_with_variant_of_appears_in_list(self, client, db):
        """A conversion that is also a variant of another conversion still appears."""
        source = make_machine_model(name="Star Trek", slug="star-trek", year=1991)
        conv_a = make_machine_model(
            name="Dark Rider",
            slug="dark-rider",
            converted_from=source,
        )
        make_machine_model(
            name="Dark Rider LE",
            slug="dark-rider-le",
            converted_from=source,
            variant_of=conv_a,
        )
        resp = client.get("/api/models/")
        data = resp.json()
        names = [m["name"] for m in data["items"]]
        assert "Dark Rider LE" in names
        assert "Dark Rider" in names
        assert "Star Trek" in names

    def test_get_model_404(self, client, db):
        resp = client.get("/api/pages/model/nonexistent")
        assert resp.status_code == 404

    def test_recent_models_returns_expected_data(self, client, machine_model):
        resp = client.get("/api/models/recent/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Medieval Madness"
        assert data[0]["slug"] == "medieval-madness"
        assert data[0]["manufacturer_name"] == "Williams"
        assert data[0]["year"] == 1997

    def test_recent_models_query_is_bounded(self, client, db):
        """The /recent/ query must use LIMIT to avoid fetching all rows."""
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            resp = client.get("/api/models/recent/")
        assert resp.status_code == 200
        model_queries = [
            q["sql"] for q in ctx.captured_queries if "catalog_machinemodel" in q["sql"]
        ]
        assert model_queries, "Expected at least one query on catalog_machinemodel"
        assert any("LIMIT" in q.upper() for q in model_queries), (
            f"Expected LIMIT in query, got: {model_queries[0][:200]}"
        )


@pytest.mark.django_db
class TestModelDetailAbbreviations:
    """The model-detail endpoint hides Title-owned abbreviations at read time
    (live dedup over claim-faithful materialized rows)."""

    def test_detail_hides_title_owned_abbreviation(self, client):
        title = Title.objects.create(name="Medieval Madness", slug="mm-title")
        pm = make_machine_model(name="MM", slug="mm-model", title=title)
        TitleAbbreviation.objects.create(title=title, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="TS4LE")

        data = client.get(f"/api/pages/model/{pm.slug}").json()
        assert data["abbreviations"] == ["TS4LE"]

    def test_non_overlapping_abbreviations_all_shown(self, client):
        title = Title.objects.create(name="Medieval Madness", slug="mm-title")
        pm = make_machine_model(name="MM", slug="mm-model", title=title)
        TitleAbbreviation.objects.create(title=title, value="MM")
        ModelAbbreviation.objects.create(machine_model=pm, value="TS4LE")

        data = client.get(f"/api/pages/model/{pm.slug}").json()
        assert data["abbreviations"] == ["TS4LE"]

    def test_title_abbreviation_removal_is_live(self, client):
        """The headline staleness fix: removing a Title's abbreviation surfaces
        on its models immediately, without re-resolving each model."""
        ipdb = make_ingest_source(name="IPDB", source_type="database", priority=10)
        editorial = make_ingest_source(
            name="Editorial", source_type="editorial", priority=100
        )
        title = Title.objects.create(name="Medieval Madness", slug="mm-title")
        pm = make_machine_model(name="MM", slug="mm-model", title=title)

        abbr_key, abbr_val = build_relationship_claim("abbreviation", {"value": "MM"})
        ts4_key, ts4_val = build_relationship_claim("abbreviation", {"value": "TS4LE"})
        make_claim(
            title, "abbreviation", abbr_val, ingest_source=ipdb, claim_key=abbr_key
        )
        make_claim(pm, "abbreviation", abbr_val, ingest_source=ipdb, claim_key=abbr_key)
        make_claim(pm, "abbreviation", ts4_val, ingest_source=ipdb, claim_key=ts4_key)

        resolve_relationship(Title, "abbreviation")
        resolve_relationship(MachineModel, "abbreviation")

        # Initially "MM" is hidden — the Title owns it.
        data = client.get(f"/api/pages/model/{pm.slug}").json()
        assert data["abbreviations"] == ["TS4LE"]

        # Remove the Title's "MM" and re-resolve ONLY title abbreviations.
        gone_key, gone_val = build_relationship_claim(
            "abbreviation", {"value": "MM"}, exists=False
        )
        make_claim(
            title, "abbreviation", gone_val, ingest_source=editorial, claim_key=gone_key
        )
        resolve_relationship(Title, "abbreviation")

        # The model now shows "MM" live — no model re-resolve happened.
        data = client.get(f"/api/pages/model/{pm.slug}").json()
        assert sorted(data["abbreviations"]) == ["MM", "TS4LE"]
