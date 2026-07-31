"""Tests for /api/pages/ endpoints that have no migrated coverage from old detail GETs."""

import pytest

from apps.catalog.models import (
    Cabinet,
    DisplaySubtype,
    DisplayType,
    Franchise,
    GameFormat,
    GameplayFeature,
    RewardType,
    Series,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
    Title,
)

# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSeriesPageEndpoint:
    def test_returns_series(self, client, db):
        title = Title.objects.create(name="Eight Ball Deluxe", slug="eight-ball-deluxe")
        s = Series.objects.create(name="Eight Ball", slug="eight-ball")
        title.series_id = s.pk
        title.save(update_fields=["series"])
        resp = client.get("/api/pages/series/eight-ball")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Eight Ball"
        assert data["slug"] == "eight-ball"
        assert len(data["titles"]) == 1
        assert data["titles"][0]["name"] == "Eight Ball Deluxe"

    def test_404(self, client, db):
        assert client.get("/api/pages/series/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Gameplay Features
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGameplayFeaturePageEndpoint:
    def test_returns_feature(self, client, db):
        GameplayFeature.objects.create(name="Multiball", slug="multiball")
        resp = client.get("/api/pages/gameplay-feature/multiball")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Multiball"
        assert data["slug"] == "multiball"

    def test_404(self, client, db):
        assert client.get("/api/pages/gameplay-feature/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Franchises
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFranchisePageEndpoint:
    def test_returns_franchise(self, client, db):
        f = Franchise.objects.create(name="Star Trek", slug="star-trek")
        title = Title.objects.create(name="Star Trek TNG", slug="star-trek-tng")
        title.franchise_id = f.pk
        title.save(update_fields=["franchise"])
        resp = client.get("/api/pages/franchise/star-trek")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Star Trek"
        assert len(data["titles"]) == 1

    def test_404(self, client, db):
        assert client.get("/api/pages/franchise/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestThemePageEndpoint:
    def test_returns_theme(self, client, db):
        Theme.objects.create(name="Medieval", slug="medieval")
        resp = client.get("/api/pages/theme/medieval")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Medieval"
        assert data["slug"] == "medieval"

    def test_404(self, client, db):
        assert client.get("/api/pages/theme/nonexistent").status_code == 404

    def test_embeds_page_one_of_the_listing(self, client, db):
        """The embed *is* the listing pinned to the dimension: same cards, same
        count as ``GET /api/games/?theme=`` — descendants included (the page no
        longer lists direct tags only) and rolled up (a unanimous Title
        absorbs its Models)."""
        from apps.catalog.tests.game_builders import _model, _theme, _title

        medieval = _theme("medieval")
        _theme("castles", parents=(medieval,))
        t1 = _title("Excalibur", "excalibur")
        _model(t1, "excalibur-m", themes=("medieval",), year=1988)
        t2 = _title("Camelot", "camelot")
        _model(t2, "camelot-m", themes=("castles",), year=1990)  # child theme
        _title("Unthemed", "unthemed")

        page = client.get("/api/pages/theme/medieval").json()
        listing = client.get("/api/games/?theme=medieval").json()
        assert page["games"] == listing
        assert page["games"]["count"] == 2
        assert [c["name"] for c in page["games"]["items"]] == ["Camelot", "Excalibur"]
        assert {c["entity_type"] for c in page["games"]["items"]} == {"title"}

    def test_embed_honors_q(self, client, db):
        """The detail page's search box narrows the same pinned listing call."""
        from apps.catalog.tests.game_builders import _model, _theme, _title

        _theme("medieval")
        t1 = _title("Excalibur", "excalibur")
        _model(t1, "excalibur-m", themes=("medieval",))
        t2 = _title("Camelot", "camelot")
        _model(t2, "camelot-m", themes=("medieval",))

        data = client.get("/api/pages/theme/medieval?q=excal").json()
        assert data["games"]["count"] == 1
        assert data["games"]["items"][0]["name"] == "Excalibur"
        # The entity's own fields are unaffected by q.
        assert data["name"] == "Medieval"


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTagPageEndpoint:
    def test_returns_tag(self, client, db):
        Tag.objects.create(name="Classic", slug="classic")
        resp = client.get("/api/pages/tag/classic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Classic"
        assert data["slug"] == "classic"

    def test_404(self, client, db):
        assert client.get("/api/pages/tag/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Cabinets
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCabinetPageEndpoint:
    def test_returns_cabinet(self, client, db):
        Cabinet.objects.create(name="Standard Body", slug="standard-body")
        resp = client.get("/api/pages/cabinet/standard-body")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Standard Body"

    def test_404(self, client, db):
        assert client.get("/api/pages/cabinet/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Display Types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDisplayTypePageEndpoint:
    def test_returns_display_type(self, client, db):
        DisplayType.objects.create(name="Dot Matrix", slug="dot-matrix")
        resp = client.get("/api/pages/display-type/dot-matrix")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Dot Matrix"

    def test_404(self, client, db):
        assert client.get("/api/pages/display-type/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Display Subtypes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDisplaySubtypePageEndpoint:
    def test_returns_display_subtype(self, client, db):
        dt = DisplayType.objects.create(name="Dot Matrix", slug="dot-matrix")
        DisplaySubtype.objects.create(name="128x32", slug="128x32", display_type=dt)
        resp = client.get("/api/pages/display-subtype/128x32")
        assert resp.status_code == 200
        assert resp.json()["name"] == "128x32"

    def test_404(self, client, db):
        assert client.get("/api/pages/display-subtype/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Game Formats
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGameFormatPageEndpoint:
    def test_returns_game_format(self, client, db):
        GameFormat.objects.create(name="Single Player", slug="single-player")
        resp = client.get("/api/pages/game-format/single-player")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Single Player"

    def test_404(self, client, db):
        assert client.get("/api/pages/game-format/nonexistent").status_code == 404

    def test_embed_is_raw_unclassified_never_matches(self, client, db):
        """The sparse dimension enters raw: the page lists only the classified
        minority. The default-bucket widening is PR.SPARSE, not this."""
        from apps.catalog.tests.game_builders import _model, _title

        t1 = _title("Classified", "classified")
        _model(t1, "classified-m", game_format="pinball")
        t2 = _title("Unclassified", "unclassified")
        _model(t2, "unclassified-m")
        data = client.get("/api/pages/game-format/pinball").json()
        assert [c["name"] for c in data["games"]["items"]] == ["Classified"]


# ---------------------------------------------------------------------------
# Production Statuses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProductionStatusPageEndpoint:
    def test_variant_with_own_status_cards_beside_its_parent(self, client, db):
        """What the deleted ``include_variants`` flag existed for, preserved by
        the roll-up: an announced LE Variant of a shipped parent surfaces on
        the announced page by construction — the parent fails the dimension,
        so it absorbs nothing."""
        from apps.catalog.tests.game_builders import (
            _model,
            _production_status,
            _title,
        )

        _production_status("announced")
        t = _title("Tiered", "tiered")
        parent = _model(t, "tiered-premium", name="Tiered Premium")
        _model(
            t,
            "tiered-le",
            name="Tiered LE",
            variant_of=parent,
            production_status="announced",
        )
        data = client.get("/api/pages/production-status/announced").json()
        assert [(c["entity_type"], c["name"]) for c in data["games"]["items"]] == [
            ("model", "Tiered LE")
        ]


# ---------------------------------------------------------------------------
# Reward Types
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRewardTypePageEndpoint:
    def test_returns_reward_type(self, client, db):
        RewardType.objects.create(name="Extra Ball", slug="extra-ball")
        resp = client.get("/api/pages/reward-type/extra-ball")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Extra Ball"
        assert "machines" in data

    def test_404(self, client, db):
        assert client.get("/api/pages/reward-type/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Technology Generations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTechnologyGenerationPageEndpoint:
    def test_returns_technology_generation(self, client, db):
        TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        resp = client.get("/api/pages/technology-generation/solid-state")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Solid State"

    def test_404(self, client, db):
        assert (
            client.get("/api/pages/technology-generation/nonexistent").status_code
            == 404
        )


# ---------------------------------------------------------------------------
# Technology Subgenerations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTechnologySubgenerationPageEndpoint:
    def test_returns_technology_subgeneration(self, client, db):
        tg = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        TechnologySubgeneration.objects.create(
            name="Early SS", slug="early-ss", technology_generation=tg
        )
        resp = client.get("/api/pages/technology-subgeneration/early-ss")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Early SS"

    def test_embed_matches_directly_or_through_system(self, client, db):
        """The OR arm travels to the page: a Model in the subgeneration via its
        system lists beside one carrying the FK directly."""
        from apps.catalog.tests.game_builders import _model, _subgen, _system, _title

        _subgen("mpu")
        t1 = _title("Direct", "direct")
        _model(t1, "direct-m", subgen="mpu")
        t2 = _title("Via System", "via-system")
        sys = _system("wpc-95")
        sys.technology_subgeneration = _subgen("mpu")
        sys.save()
        _model(t2, "via-system-m", system="wpc-95")
        data = client.get("/api/pages/technology-subgeneration/mpu").json()
        assert {c["name"] for c in data["games"]["items"]} == {"Direct", "Via System"}

    def test_404(self, client, db):
        assert (
            client.get("/api/pages/technology-subgeneration/nonexistent").status_code
            == 404
        )
