import pytest

from apps.accounts.test_factories import make_user
from apps.catalog.models import (
    LicenseStatus,
    MachineModel,
    ModelRelationship,
    RelationshipType,
    Title,
)
from apps.catalog.tests.conftest import make_machine_model

from .conftest import SAMPLE_IMAGES


class TestTitlesAPI:
    @pytest.fixture
    def title(self, db):
        return Title.objects.create(
            name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4"
        )

    @pytest.fixture
    def title_with_machines(self, title, williams_entity):
        make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            corporate_entity=williams_entity,
            year=1997,
            title=title,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        make_machine_model(
            name="Medieval Madness (Remake)",
            slug="medieval-madness-remake",
            corporate_entity=williams_entity,
            year=2015,
            title=title,
        )
        return title

    def test_list_titles(self, client, title_with_machines):
        resp = client.get("/api/titles/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        item = data["items"][0]
        assert item["name"] == "Medieval Madness"
        assert item["model_count"] == 2
        # Slim card shape — no facet arrays (those live on /api/pages/titles).
        assert "abbreviations" not in item
        assert "themes" not in item
        assert set(item) == {
            "name",
            "slug",
            "year",
            "model_count",
            "manufacturer",
            "thumbnail_url",
        }

    def test_list_titles_thumbnail(self, client, title_with_machines):
        resp = client.get("/api/titles/")
        data = resp.json()
        assert data["items"][0]["thumbnail_url"] == "https://img.opdb.org/md.jpg"

    def test_list_titles_empty_title(self, client, title):
        resp = client.get("/api/titles/")
        data = resp.json()
        assert data["items"][0]["model_count"] == 0
        assert data["items"][0]["thumbnail_url"] is None

    def test_q_search_matches_name(self, client, title):
        # title == "Medieval Madness"
        assert client.get("/api/titles/?q=medieval").json()["count"] == 1
        assert client.get("/api/titles/?q=Madness").json()["count"] == 1
        assert client.get("/api/titles/?q=nonexistent").json()["count"] == 0

    def test_q_search_diacritic_is_backend_specific(self, client, db):
        """Title-name `q` folds diacritics on Postgres only.

        Pins the deliberate dev/prod difference: prod (Postgres) folds via
        LOWER(UNACCENT(name)) so "pokemon" finds "Pokémon"; dev/CI (SQLite) does
        plain icontains, so it does not. The exact-diacritic spelling matches on
        both.
        """
        from django.db import connection

        Title.objects.create(name="Pokémon", slug="pokemon-diacritic-test")
        folded = client.get("/api/titles/?q=pokemon").json()["count"]
        exact = client.get("/api/titles/?q=Pokémon").json()["count"]
        assert exact == 1
        assert folded == (1 if connection.vendor == "postgresql" else 0)

    def test_get_title_detail(self, client, title_with_machines):
        resp = client.get(f"/api/pages/title/{title_with_machines.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Medieval Madness"
        assert len(data["machines"]) == 2

    def test_get_title_detail_excludes_variants(self, client, title_with_machines):
        parent = MachineModel.objects.get(name="Medieval Madness")
        make_machine_model(
            name="Medieval Madness (LE)",
            slug="medieval-madness-le",
            title=title_with_machines,
            variant_of=parent,
        )
        resp = client.get(f"/api/pages/title/{title_with_machines.slug}")
        data = resp.json()
        assert len(data["machines"]) == 2
        names = [m["name"] for m in data["machines"]]
        assert "Medieval Madness (LE)" not in names

    def test_title_detail_excludes_deleted_variants(self, client, title_with_machines):
        # A soft-deleted variant (its delete is never blocked) must not render
        # a nested variant card — same reverse-liveness rule as the model page.
        parent = MachineModel.objects.get(name="Medieval Madness")
        make_machine_model(
            name="Medieval Madness (Zombie LE)",
            slug="medieval-madness-zombie-le",
            title=title_with_machines,
            variant_of=parent,
            status="deleted",
        )
        resp = client.get(f"/api/pages/title/{title_with_machines.slug}")
        data = resp.json()
        variants = [v for m in data["machines"] for v in m.get("variants", [])]
        assert variants == []

    def test_model_count_excludes_variants(self, client, title_with_machines):
        parent = MachineModel.objects.get(name="Medieval Madness")
        make_machine_model(
            name="Medieval Madness (LE)",
            slug="medieval-madness-le",
            title=title_with_machines,
            variant_of=parent,
        )
        resp = client.get("/api/titles/")
        data = resp.json()
        assert data["items"][0]["model_count"] == 2

    def test_get_title_404(self, client, db):
        resp = client.get("/api/pages/title/nonexistent")
        assert resp.status_code == 404

    def test_get_title_sources_page(self, client, title):
        resp = client.get(f"/api/pages/sources/title/{title.slug}/")
        assert resp.status_code == 200
        body = resp.json()
        assert "sources" in body
        assert "evidence" in body


class TestTitleDetailAggregation:
    """Aggregation rules for the multi-model title reader view:
    scalars/M2Ms intersect, media/related_titles union."""

    @pytest.fixture
    def title(self, db):
        return Title.objects.create(
            name="Medieval Madness",
            slug="medieval-madness",
            opdb_id="G5pe4",
            fandom_page_id=12345,
        )

    def test_opdb_id_and_fandom_page_id_exposed(self, client, title):
        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()
        assert data["opdb_id"] == "G5pe4"
        assert data["fandom_page_id"] == 12345

    def test_technology_subgeneration_intersection_agrees(
        self, client, title, williams_entity, solid_state
    ):
        from apps.catalog.models import TechnologySubgeneration

        subgen = TechnologySubgeneration.objects.create(
            name="WPC-95",
            slug="wpc-95-sub",
            technology_generation=solid_state,
        )
        make_machine_model(
            name="MM", slug="mm-1", title=title, technology_subgeneration=subgen
        )
        make_machine_model(
            name="MMR", slug="mm-2", title=title, technology_subgeneration=subgen
        )
        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()
        assert (
            data["agreed_specs"]["technology_subgeneration"]["public_id"]
            == "wpc-95-sub"
        )

    def test_technology_subgeneration_intersection_disagrees(
        self, client, title, solid_state
    ):
        from apps.catalog.models import TechnologySubgeneration

        sg1 = TechnologySubgeneration.objects.create(
            name="WPC", slug="wpc", technology_generation=solid_state
        )
        sg2 = TechnologySubgeneration.objects.create(
            name="SAM", slug="sam", technology_generation=solid_state
        )
        make_machine_model(
            name="MM", slug="mm-1", title=title, technology_subgeneration=sg1
        )
        make_machine_model(
            name="MMR", slug="mm-2", title=title, technology_subgeneration=sg2
        )
        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()
        assert data["agreed_specs"].get("technology_subgeneration") is None

    def test_tags_intersection(self, client, title):
        from apps.catalog.models import Tag

        common = Tag.objects.create(name="Classic", slug="classic")
        only_one = Tag.objects.create(name="LE", slug="le")
        m1 = make_machine_model(name="MM", slug="mm-1", title=title)
        m2 = make_machine_model(name="MMR", slug="mm-2", title=title)
        m1.tags.add(common, only_one)
        m2.tags.add(common)
        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()
        tag_slugs = [t["public_id"] for t in data["agreed_specs"]["tags"]]
        assert tag_slugs == ["classic"]  # only the shared one

    def test_related_titles_union_cross_title_only(self, client, db):
        """`remake_of` pointing to an *other* title appears; same-title
        relations do not."""
        other_title = Title.objects.create(name="Star Trek", slug="star-trek")
        other_model = make_machine_model(
            name="Star Trek", slug="star-trek-orig", title=other_title
        )

        this_title = Title.objects.create(name="Dark Rider", slug="dark-rider")
        m_cross = make_machine_model(
            name="Dark Rider",
            slug="dark-rider-1",
            title=this_title,
            remake_of=other_model,
        )
        # Within-title remake — should NOT appear in related_titles.
        make_machine_model(
            name="Dark Rider B",
            slug="dark-rider-2",
            title=this_title,
            remake_of=m_cross,
        )

        resp = client.get(f"/api/pages/title/{this_title.slug}")
        data = resp.json()
        related = data["related_titles"]
        assert len(related) == 1
        assert related[0]["relation"] == "remake_of"
        assert related[0]["other_title"]["public_id"] == "star-trek"
        assert related[0]["source_model"]["public_id"] == "dark-rider-1"

    def test_related_titles_union_across_models(self, client, db):
        """Two different models each contribute a cross-title link — one via
        the `remake_of` FK, one via a conversion edge."""
        orig = Title.objects.create(name="Orig A", slug="orig-a")
        orig_m = make_machine_model(name="Orig A", slug="orig-a-1", title=orig)
        remake_src = Title.objects.create(name="Remake Src", slug="remake-src")
        remake_src_m = make_machine_model(
            name="Remake Src", slug="remake-src-1", title=remake_src
        )

        this_title = Title.objects.create(name="Compound", slug="compound")
        c1 = make_machine_model(name="C1", slug="c-1", title=this_title)
        ModelRelationship.objects.create(
            machine_model=c1,
            target_machine=orig_m,
            relationship_type=RelationshipType.CONVERSION,
        )
        make_machine_model(
            name="C2", slug="c-2", title=this_title, remake_of=remake_src_m
        )

        resp = client.get(f"/api/pages/title/{this_title.slug}")
        data = resp.json()
        related = data["related_titles"]
        relations = sorted(
            (r["relation"], r["other_title"]["public_id"]) for r in related
        )
        assert relations == [
            ("conversion", "orig-a"),
            ("remake_of", "remake-src"),
        ]

    def test_related_titles_from_relationship_edges(self, client, db):
        """Machine-target edges contribute cross-title lines with their license;
        same-title edges and label-target edges do not; two same-kind edges
        landing on the same other title collapse to one line."""
        orig_title = Title.objects.create(name="Galaxie", slug="galaxie")
        orig_a = make_machine_model(name="Galaxie", slug="galaxie", title=orig_title)
        orig_b = make_machine_model(
            name="Galaxie II", slug="galaxie-ii", title=orig_title
        )

        this_title = Title.objects.create(name="Galaxie RMG", slug="galaxie-rmg")
        rmg = make_machine_model(name="Galaxie", slug="galaxie-rmg-1", title=this_title)
        sibling = make_machine_model(
            name="Galaxie B", slug="galaxie-rmg-2", title=this_title
        )

        # Two copy edges onto two machines of the same other title → one line.
        ModelRelationship.objects.create(
            machine_model=rmg,
            target_machine=orig_a,
            relationship_type=RelationshipType.COPY,
            license_status=LicenseStatus.UNLICENSED,
        )
        ModelRelationship.objects.create(
            machine_model=rmg,
            target_machine=orig_b,
            relationship_type=RelationshipType.COPY,
            license_status=LicenseStatus.UNLICENSED,
        )
        # Same-title edge — not cross-title content.
        ModelRelationship.objects.create(
            machine_model=rmg,
            target_machine=sibling,
            relationship_type=RelationshipType.CONVERSION,
        )
        # Label target — no title to link.
        ModelRelationship.objects.create(
            machine_model=rmg,
            target_label="several Gottlieb EM models",
            relationship_type=RelationshipType.CONVERSION_KIT,
        )

        data = client.get(f"/api/pages/title/{this_title.slug}").json()
        related = data["related_titles"]
        assert len(related) == 1
        assert related[0]["relation"] == "copy"
        assert related[0]["license_status"] == "unlicensed"
        assert related[0]["other_title"]["public_id"] == "galaxie"
        assert related[0]["source_model"]["public_id"] == "galaxie-rmg-1"

    def test_related_titles_export_edition_fk(self, client, db):
        """A cross-title `export_edition_of` link (the Dragon/Dragoon shape —
        twin pairs don't always share a Title) contributes its line; a
        same-title export edition does not."""
        domestic_title = Title.objects.create(name="Dragoon", slug="dragoon")
        domestic = make_machine_model(
            name="Dragoon", slug="dragoon-1", title=domestic_title
        )
        this_title = Title.objects.create(name="Dragon", slug="dragon")
        export = make_machine_model(name="Dragon", slug="dragon-1", title=this_title)
        export.export_edition_of = domestic
        export.save(update_fields=["export_edition_of"])
        # Same-title export edition — not cross-title content.
        sibling = make_machine_model(
            name="Dragon (Italy)", slug="dragon-italy", title=this_title
        )
        sibling.export_edition_of = export
        sibling.save(update_fields=["export_edition_of"])

        data = client.get(f"/api/pages/title/{this_title.slug}").json()
        related = data["related_titles"]
        assert len(related) == 1
        assert related[0]["relation"] == "export_edition_of"
        assert related[0]["other_title"]["public_id"] == "dragoon"
        assert related[0]["source_model"]["public_id"] == "dragon-1"

    def test_related_titles_retheme_edge(self, client, db):
        """A re-theme's donor nearly always sits under its own Title (38 of the
        39 seeded edges), so the cross-title path is a re-theme's normal read —
        the regression guarding the CrossTitleRelation literal against a missing
        edge type."""
        donor_title = Title.objects.create(name="Earthshaker", slug="earthshaker")
        donor = make_machine_model(
            name="Earthshaker", slug="earthshaker", title=donor_title
        )
        this_title = Title.objects.create(name="Metallica Retheme", slug="metallica-rt")
        subject = make_machine_model(
            name="Metallica", slug="metallica-rt-1", title=this_title
        )
        ModelRelationship.objects.create(
            machine_model=subject,
            target_machine=donor,
            relationship_type=RelationshipType.RETHEME,
            license_status=LicenseStatus.UNLICENSED,
        )

        data = client.get(f"/api/pages/title/{this_title.slug}").json()
        related = data["related_titles"]
        assert len(related) == 1
        assert related[0]["relation"] == "retheme"
        assert related[0]["license_status"] == "unlicensed"
        assert related[0]["other_title"]["public_id"] == "earthshaker"

    def test_related_titles_remake_fk_alongside_edges(self, client, db):
        """The permanent `remake_of` FK and relationship edges contribute
        lines to the same panel."""
        donor_title = Title.objects.create(name="Team One", slug="team-one")
        donor = make_machine_model(name="Team One", slug="team-one", title=donor_title)

        this_title = Title.objects.create(name="Wizard", slug="wizard")
        make_machine_model(
            name="Wizard",
            slug="wizard-1",
            title=this_title,
            remake_of=donor,
        )
        kit = make_machine_model(name="Wizard Kit", slug="wizard-2", title=this_title)
        ModelRelationship.objects.create(
            machine_model=kit,
            target_machine=donor,
            relationship_type=RelationshipType.CONVERSION_KIT,
            license_status=LicenseStatus.LICENSED,
        )

        data = client.get(f"/api/pages/title/{this_title.slug}").json()
        relations = sorted(
            (r["relation"], r["source_model"]["public_id"], r["license_status"])
            for r in data["related_titles"]
        )
        assert relations == [
            ("conversion_kit", "wizard-2", "licensed"),
            ("remake_of", "wizard-1", "unknown"),
        ]

    def test_media_aggregation_empty_by_default(self, client, title, williams_entity):
        make_machine_model(name="MM", slug="mm-1", title=title)
        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()
        assert data["media"] == []

    def test_media_aggregation_union_with_source_model(self, client, db, title):
        from django.contrib.contenttypes.models import ContentType

        from apps.media.models import EntityMedia, MediaAsset

        user = make_user(email="u@example.com")
        m1 = make_machine_model(name="MM", slug="mm-1", title=title)
        m2 = make_machine_model(name="MMR", slug="mm-2", title=title)
        ct = ContentType.objects.get_for_model(MachineModel)

        a1 = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="a.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )
        a2 = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="b.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )
        EntityMedia.objects.create(
            content_type=ct,
            object_id=m1.pk,
            asset=a1,
            category="backglass",
            is_primary=True,
        )
        EntityMedia.objects.create(
            content_type=ct,
            object_id=m2.pk,
            asset=a2,
            category="playfield",
            is_primary=False,
        )

        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()
        media = data["media"]
        assert len(media) == 2
        by_source = {item["source_model"]["public_id"]: item for item in media}
        assert by_source["mm-1"]["category"] == "backglass"
        assert by_source["mm-1"]["is_primary"] is True
        assert by_source["mm-2"]["category"] == "playfield"
        assert by_source["mm-1"]["asset_uuid"] == str(a1.uuid)
        assert "thumb" in by_source["mm-1"]["renditions"]
        assert "display" in by_source["mm-1"]["renditions"]

    def test_title_hero_uses_earliest_model_with_backglass_photo(
        self, client, db, title
    ):
        from django.contrib.contenttypes.models import ContentType

        from apps.media.models import EntityMedia, MediaAsset
        from apps.media.storage import build_public_url, build_storage_key

        user = make_user(email="u@example.com")
        earliest = make_machine_model(
            name="MM",
            slug="mm-1",
            title=title,
            year=1990,
        )
        middle = make_machine_model(
            name="MMR",
            slug="mm-2",
            title=title,
            year=1991,
        )
        latest = make_machine_model(
            name="MM Deluxe",
            slug="mm-3",
            title=title,
            year=1992,
        )
        ct = ContentType.objects.get_for_model(MachineModel)

        playfield_asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="playfield.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )
        backglass_asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="backglass.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )
        later_playfield_asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="later-playfield.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )

        EntityMedia.objects.create(
            content_type=ct,
            object_id=earliest.pk,
            asset=playfield_asset,
            category="playfield",
            is_primary=True,
        )
        EntityMedia.objects.create(
            content_type=ct,
            object_id=middle.pk,
            asset=backglass_asset,
            category="backglass",
            is_primary=True,
        )
        EntityMedia.objects.create(
            content_type=ct,
            object_id=latest.pk,
            asset=later_playfield_asset,
            category="playfield",
            is_primary=True,
        )

        resp = client.get(f"/api/pages/title/{title.slug}")
        data = resp.json()

        assert data["hero_image_url"] == build_public_url(
            build_storage_key(backglass_asset.uuid, "display")
        )
