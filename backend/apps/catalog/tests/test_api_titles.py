import pytest
from django.core.cache import cache

from apps.accounts.test_factories import make_user
from apps.catalog.models import (
    Credit,
    CreditRole,
    DisplayType,
    Franchise,
    MachineModel,
    Person,
    Series,
    System,
    Theme,
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
        assert item["abbreviations"] == []
        assert item["model_count"] == 2

    def test_list_titles_thumbnail(self, client, title_with_machines):
        resp = client.get("/api/titles/")
        data = resp.json()
        assert data["items"][0]["thumbnail_url"] == "https://img.opdb.org/md.jpg"

    def test_list_titles_empty_title(self, client, title):
        resp = client.get("/api/titles/")
        data = resp.json()
        assert data["items"][0]["model_count"] == 0
        assert data["items"][0]["thumbnail_url"] is None

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
        """converted_from / remake_of pointing to *other* titles appear;
        same-title relations do not."""
        other_title = Title.objects.create(name="Star Trek", slug="star-trek")
        other_model = make_machine_model(
            name="Star Trek", slug="star-trek-orig", title=other_title
        )

        this_title = Title.objects.create(name="Dark Rider", slug="dark-rider")
        m_cross = make_machine_model(
            name="Dark Rider",
            slug="dark-rider-1",
            title=this_title,
            converted_from=other_model,
        )
        # Within-title "conversion" — should NOT appear in related_titles.
        make_machine_model(
            name="Dark Rider B",
            slug="dark-rider-2",
            title=this_title,
            converted_from=m_cross,
        )

        resp = client.get(f"/api/pages/title/{this_title.slug}")
        data = resp.json()
        related = data["related_titles"]
        assert len(related) == 1
        assert related[0]["relation"] == "converted_from"
        assert related[0]["other_title"]["public_id"] == "star-trek"
        assert related[0]["source_model"]["public_id"] == "dark-rider-1"

    def test_related_titles_union_across_models(self, client, db):
        """Two different models each contribute a cross-title link."""
        orig = Title.objects.create(name="Orig A", slug="orig-a")
        orig_m = make_machine_model(name="Orig A", slug="orig-a-1", title=orig)
        remake_src = Title.objects.create(name="Remake Src", slug="remake-src")
        remake_src_m = make_machine_model(
            name="Remake Src", slug="remake-src-1", title=remake_src
        )

        this_title = Title.objects.create(name="Compound", slug="compound")
        make_machine_model(
            name="C1", slug="c-1", title=this_title, converted_from=orig_m
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
            ("converted_from", "orig-a"),
            ("remake_of", "remake-src"),
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


class TestTitlesAllFacets:
    """Test that /api/titles/all/ returns enriched facet data."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    @pytest.fixture
    def faceted_title(
        self, db, manufacturer, williams_entity, solid_state, credit_roles
    ):
        title = Title.objects.create(
            name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4"
        )
        franchise = Franchise.objects.create(name="Castle Games", slug="castle-games")
        title.franchise_id = franchise.pk
        title.save()
        series = Series.objects.create(name="Castle Series", slug="castle-series")
        title.series_id = series.pk
        title.save()

        dmd = DisplayType.objects.create(name="DMD", slug="dmd")
        wpc = System.objects.create(
            name="WPC-95", slug="wpc-95", manufacturer=manufacturer
        )
        person = Person.objects.create(name="Pat Lawlor", slug="pat-lawlor")
        theme = Theme.objects.create(name="Medieval", slug="medieval")
        role = CreditRole.objects.get(slug="design")

        m1 = make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            corporate_entity=williams_entity,
            year=1997,
            title=title,
            technology_generation=solid_state,
            display_type=dmd,
            system=wpc,
            player_count=4,
            ipdb_rating=8.5,
        )
        m1.themes.add(theme)
        Credit.objects.create(model=m1, person=person, role=role)

        # Second model with different year to test year_min/year_max
        make_machine_model(
            name="Medieval Madness (Remake)",
            slug="medieval-madness-remake",
            corporate_entity=williams_entity,
            year=2015,
            title=title,
            technology_generation=solid_state,
            player_count=4,
        )
        return title

    def test_all_titles_returns_facet_fields(self, client, faceted_title):
        resp = client.get("/api/titles/all/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]

        # Basic fields
        assert item["name"] == "Medieval Madness"
        assert item["manufacturer"]["public_id"] == "williams"

        # Tech generations
        assert len(item["tech_generations"]) == 1
        assert item["tech_generations"][0]["public_id"] == "solid-state"

        # Display types
        assert len(item["display_types"]) == 1
        assert item["display_types"][0]["public_id"] == "dmd"

        # Player counts
        assert item["player_counts"] == [4]

        # Systems
        assert len(item["systems"]) == 1
        assert item["systems"][0]["public_id"] == "wpc-95"

        # Themes
        assert len(item["themes"]) == 1
        assert item["themes"][0]["public_id"] == "medieval"

        # Persons
        assert len(item["persons"]) == 1
        assert item["persons"][0]["public_id"] == "pat-lawlor"

        # Franchise
        assert item["franchise"]["public_id"] == "castle-games"

        # Series
        assert item["series"]["public_id"] == "castle-series"

        # Year range from two models (1997 and 2015)
        assert item["year_min"] == 1997
        assert item["year_max"] == 2015

        # Rating
        assert item["ipdb_rating_max"] == 8.5

    def test_all_titles_deduplicates_tech_generations(self, client, faceted_title):
        """Two models with the same tech gen should yield one entry."""
        resp = client.get("/api/titles/all/")
        data = resp.json()
        # Both models are solid-state, but should be deduped to 1
        assert len(data[0]["tech_generations"]) == 1

    def test_all_titles_excludes_variant_models(self, client, faceted_title):
        """Variant models should not contribute facet data."""
        parent = MachineModel.objects.get(name="Medieval Madness")
        lcd = DisplayType.objects.create(name="LCD", slug="lcd")
        make_machine_model(
            name="Medieval Madness (LE)",
            slug="medieval-madness-le",
            title=faceted_title,
            variant_of=parent,
            display_type=lcd,
        )
        resp = client.get("/api/titles/all/")
        data = resp.json()
        display_slugs = [d["public_id"] for d in data[0]["display_types"]]
        assert "lcd" not in display_slugs

    def test_all_titles_thumbnail_prefers_uploaded_backglass(
        self, client, db, williams_entity
    ):
        """A title's primary model with an uploaded backglass returns the
        upload's thumb URL on the /all/ endpoint, not the extra_data URL."""
        from django.contrib.contenttypes.models import ContentType

        from apps.media.models import EntityMedia, MediaAsset
        from apps.media.storage import build_public_url, build_storage_key

        title = Title.objects.create(name="MM", slug="mm", opdb_id="MM")
        pm = make_machine_model(
            name="MM",
            slug="mm-1",
            title=title,
            corporate_entity=williams_entity,
            year=1997,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        user = make_user(email="up@example.com")
        asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="bg.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )
        EntityMedia.objects.create(
            content_type=ContentType.objects.get_for_model(MachineModel),
            object_id=pm.pk,
            asset=asset,
            category="backglass",
            is_primary=True,
        )

        resp = client.get("/api/titles/all/")
        data = resp.json()
        item = next(i for i in data if i["slug"] == "mm")
        expected = build_public_url(build_storage_key(asset.uuid, "thumb"))
        assert item["thumbnail_url"] == expected

    def test_all_titles_thumbnail_falls_back_to_extra_data(
        self, client, db, williams_entity
    ):
        """No upload → existing OPDB thumbnail URL still wins."""
        title = Title.objects.create(name="MM2", slug="mm2", opdb_id="MM2")
        make_machine_model(
            name="MM2",
            slug="mm2-1",
            title=title,
            corporate_entity=williams_entity,
            year=1997,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        resp = client.get("/api/titles/all/")
        data = resp.json()
        item = next(i for i in data if i["slug"] == "mm2")
        assert item["thumbnail_url"] == "https://img.opdb.org/md.jpg"

    def test_all_titles_cache_invalidates_on_media_attachment_resolve(
        self,
        client,
        db,
        williams_entity,
        django_capture_on_commit_callbacks,
    ):
        """Resolving a media_attachment claim busts the cached /all/ payload
        so the next call reflects the new thumbnail.  Mirrors the production
        upload path, which writes EntityMedia via bulk_create (no post_save)
        and relies on transaction.on_commit(invalidate_all) inside the
        resolver.
        """
        from django.contrib.contenttypes.models import ContentType

        from apps.catalog.claims import build_media_attachment_claim
        from apps.catalog.resolve import resolve_media_attachments
        from apps.media.models import MediaAsset
        from apps.media.storage import build_public_url, build_storage_key
        from apps.provenance.models import Claim

        title = Title.objects.create(name="MM3", slug="mm3", opdb_id="MM3")
        pm = make_machine_model(
            name="MM3",
            slug="mm3-1",
            title=title,
            corporate_entity=williams_entity,
            year=1997,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )

        # Prime the cache with the third-party thumbnail.
        resp = client.get("/api/titles/all/")
        item = next(i for i in resp.json() if i["slug"] == "mm3")
        assert item["thumbnail_url"] == "https://img.opdb.org/md.jpg"

        user = make_user(email="up3@example.com")
        asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="bg.jpg",
            mime_type="image/jpeg",
            byte_size=1,
            width=800,
            height=600,
            uploaded_by=user,
        )
        ct = ContentType.objects.get_for_model(MachineModel)
        claim_key, claim_value = build_media_attachment_claim(
            pm, asset.pk, category="backglass", is_primary=False
        )
        with django_capture_on_commit_callbacks(execute=True):
            Claim.objects.assert_claim(
                pm, "media_attachment", claim_value, user=user, claim_key=claim_key
            )
            resolve_media_attachments(content_type_id=ct.id, subject_ids={pm.pk})

        resp = client.get("/api/titles/all/")
        item = next(i for i in resp.json() if i["slug"] == "mm3")
        expected = build_public_url(build_storage_key(asset.uuid, "thumb"))
        assert item["thumbnail_url"] == expected

    def test_all_titles_empty_title(self, client, db):
        """Title with no models returns empty facet arrays."""
        Title.objects.create(name="Empty", slug="empty", opdb_id="EMPTY")
        resp = client.get("/api/titles/all/")
        data = resp.json()
        item = data[0]
        assert item["tech_generations"] == []
        assert item["display_types"] == []
        assert item["player_counts"] == []
        assert item["themes"] == []
        assert item["persons"] == []
        assert item["franchise"] is None
        assert item["series"] is None
        assert item["year_min"] is None
        assert item["year_max"] is None
        assert item["ipdb_rating_max"] is None
