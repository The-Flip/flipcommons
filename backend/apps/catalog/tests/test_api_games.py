"""Tests for the heterogeneous listing API (``GET /api/games/`` +
``GET /api/pages/games``).

The wire half of the card-grain roll-up: card shape (``entity_type``
discriminated, exact key set — the one assertion that catches a field being
dropped), a Model row carrying the *matched* Model's display fields, the
create-gate ``query_count`` staying blind to facets but seeing Model names,
and an N+1 guard pinning that card-grain rows add no per-row query. The
roll-up rules themselves are pinned in ``test_game_rows.py`` /
``test_game_facets.py``; facet caching in ``test_api_cache.py``.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Title
from apps.catalog.tests.conftest import SAMPLE_IMAGES, make_machine_model

CARD_KEYS = {
    "entity_type",
    "name",
    "public_id",
    "year",
    "manufacturer",
    "thumbnail_url",
    "roles",
}


class TestGamesList:
    @pytest.fixture
    def title(self, db):
        return Title.objects.create(name="Medieval Madness", slug="medieval-madness")

    @pytest.fixture
    def title_with_models(self, title, williams_entity):
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

    def test_unanimous_title_lists_one_title_card(self, client, title_with_models):
        data = client.get("/api/games/").json()
        assert data["count"] == 1
        item = data["items"][0]
        assert item["entity_type"] == "title"
        assert item["name"] == "Medieval Madness"
        # Slim card shape — exact key set, so a dropped or leaked field fails.
        assert set(item) == CARD_KEYS

    def test_title_card_displays_representative(self, client, title_with_models):
        item = client.get("/api/games/").json()["items"][0]
        # Earliest model (1997, with the sample image) is the representative.
        assert item["year"] == 1997
        assert item["thumbnail_url"] == "https://img.opdb.org/md.jpg"
        assert item["manufacturer"]["name"] == "Williams"

    def test_model_row_carries_the_matched_models_fields(
        self, client, title, williams_entity, stern_entity
    ):
        """A shattered Title cards the matching Model with its OWN year,
        manufacturer and slug — not the representative's."""
        make_machine_model(
            name="Medieval Madness",
            slug="medieval-madness",
            corporate_entity=williams_entity,
            year=1997,
            title=title,
        )
        make_machine_model(
            name="Medieval Madness (Bootleg)",
            slug="medieval-madness-bootleg",
            corporate_entity=stern_entity,
            year=2001,
            title=title,
            extra_data={"opdb.images": SAMPLE_IMAGES},
        )
        data = client.get("/api/games/?manufacturer=stern").json()
        assert data["count"] == 1
        item = data["items"][0]
        assert item["entity_type"] == "model"
        assert item["public_id"] == "medieval-madness-bootleg"
        assert item["year"] == 2001
        assert item["manufacturer"]["name"] == "Stern"
        assert item["thumbnail_url"] == "https://img.opdb.org/md.jpg"
        assert set(item) == CARD_KEYS

    def test_empty_title_cards_without_thumbnail(self, client, title):
        data = client.get("/api/games/").json()
        assert data["count"] == 1
        assert data["items"][0]["thumbnail_url"] is None
        assert data["items"][0]["year"] is None

    def test_q_matches_title_name(self, client, title):
        assert client.get("/api/games/?q=medieval").json()["count"] == 1
        assert client.get("/api/games/?q=Madness").json()["count"] == 1
        assert client.get("/api/games/?q=nonexistent").json()["count"] == 0

    def test_q_matches_model_name(self, client, title_with_models):
        """The headline fix: a Model named differently from its Title is
        reachable by its own name, as a Model card."""
        data = client.get("/api/games/?q=Remake").json()
        assert data["count"] == 1
        assert data["items"][0]["entity_type"] == "model"
        assert data["items"][0]["public_id"] == "medieval-madness-remake"

    def test_whitespace_q_is_no_filter(self, client, title):
        assert client.get("/api/games/?q=%20%20").json()["count"] == 1

    def test_q_diacritic_is_backend_specific(self, client, db):
        """Name `q` folds diacritics on Postgres only — the documented dev/prod
        gap. The exact-diacritic spelling matches on both."""
        Title.objects.create(name="Pokémon", slug="pokemon-diacritic-test")
        folded = client.get("/api/games/?q=pokemon").json()["count"]
        exact = client.get("/api/games/?q=Pokémon").json()["count"]
        assert exact == 1
        assert folded == (1 if connection.vendor == "postgresql" else 0)

    def test_query_count_is_constant_across_result_size(
        self, client, db, williams_entity
    ):
        """N+1 guard: hydration is one query per kind plus prefetches, so the
        query count must not grow with rows — including Model rows."""

        def add_rows(i: int) -> None:
            t = Title.objects.create(name=f"Scale {i}", slug=f"scale-{i}")
            make_machine_model(
                name=f"Scale {i}",
                slug=f"scale-{i}-m",
                corporate_entity=williams_entity,
                year=1990 + i,
                title=t,
                extra_data={"opdb.images": SAMPLE_IMAGES},
            )
            # A differently-named sibling so the Title shatters under q and
            # Model rows exercise their own hydration path.
            make_machine_model(
                name=f"Scale Encore {i}",
                slug=f"scale-{i}-encore",
                title=t,
            )

        def query_count() -> int:
            with CaptureQueriesContext(connection) as ctx:
                client.get("/api/games/?q=Scale%20Encore")
            return len(ctx)

        add_rows(1)
        small = query_count()
        for i in range(2, 9):
            add_rows(i)
        assert query_count() == small


class TestPersonRoles:
    """The person-contextual card annotation: `roles` is populated only when
    the `person` dimension is active — a Model card carries that person's
    roles on the Model, a Title card the deduped union across its live
    Models. The pattern future dimension-contingent annotations follow."""

    @pytest.fixture
    def credited(self, db):
        from apps.catalog.models import Credit, CreditRole
        from apps.catalog.tests.game_builders import _model, _person, _title

        design, _ = CreditRole.objects.get_or_create(
            slug="design", defaults={"name": "Design", "display_order": 10}
        )
        art, _ = CreditRole.objects.get_or_create(
            slug="artwork", defaults={"name": "Artwork", "display_order": 20}
        )
        lawlor = _person("lawlor")
        t = _title("Unified", "unified")
        a = _model(t, "unified-a", name="Unified A", year=1990)
        b = _model(t, "unified-b", name="Unified B", year=1992)
        Credit.objects.create(model=a, person=lawlor, role=design)
        Credit.objects.create(model=b, person=lawlor, role=art)
        Credit.objects.create(model=b, person=lawlor, role=design)
        return t

    def test_title_card_unions_roles_across_models(self, client, credited):
        data = client.get("/api/games/?person=lawlor").json()
        assert data["count"] == 1
        card = data["items"][0]
        assert card["entity_type"] == "title"
        # Newest Model first, roles in display order within it: 1992's
        # Design/Artwork, then 1990's Design (deduped).
        assert card["roles"] == ["Design", "Artwork"]

    def test_model_card_carries_its_own_roles(self, client, credited):
        from apps.catalog.tests.game_builders import _model

        # A third, uncredited Model shatters the Title; only B cards for the
        # combined person+year query.
        _model(credited, "unified-c", name="Unified C")
        data = client.get("/api/games/?person=lawlor&year_min=1991").json()
        assert [c["entity_type"] for c in data["items"]] == ["model"]
        assert data["items"][0]["name"] == "Unified B"
        assert data["items"][0]["roles"] == ["Design", "Artwork"]

    def test_roles_absent_without_person_dimension(self, client, credited):
        data = client.get("/api/games/").json()
        assert data["items"][0]["roles"] is None

    def test_deleted_model_credit_does_not_leak_roles(self, client, credited):
        """The liveness cleanup: a credit on a deleted Model contributes
        neither a card nor a role name."""
        from apps.catalog.models import Credit, CreditRole
        from apps.catalog.tests.game_builders import _model, _person

        translator, _ = CreditRole.objects.get_or_create(
            slug="translation", defaults={"name": "Translation", "display_order": 30}
        )
        dead = _model(credited, "unified-dead", name="Unified Dead", year=1999)
        Credit.objects.create(model=dead, person=_person("lawlor"), role=translator)
        dead.status = "deleted"
        dead.save()
        card = client.get("/api/games/?person=lawlor").json()["items"][0]
        assert card["entity_type"] == "title"
        assert "Translation" not in card["roles"]


class TestHiddenDimensionParams:
    """The hidden dimensions are honored from the query string (a dimension
    detail page pins the listing through them) while staying out of the facet
    payload — ``test_payload_shape`` below pins the absence half."""

    def test_hidden_dimension_filters_the_listing(self, client, db):
        from apps.catalog.tests.game_builders import _model, _title

        t = _title("Tagged", "tagged")
        _model(t, "tagged-m", tags=("licensed",))
        t2 = _title("Untagged", "untagged")
        _model(t2, "untagged-m")
        data = client.get("/api/games/?tag=licensed").json()
        assert [item["name"] for item in data["items"]] == ["Tagged"]
        assert data["count"] == 1

    def test_hidden_dimension_composes_with_q(self, client, db):
        from apps.catalog.tests.game_builders import _model, _title

        t = _title("Cocktail Alpha", "cocktail-alpha")
        _model(t, "cocktail-alpha-m", cabinet="cocktail")
        t2 = _title("Cocktail Beta", "cocktail-beta")
        _model(t2, "cocktail-beta-m")
        data = client.get("/api/games/?cabinet=cocktail&q=cocktail").json()
        assert [item["name"] for item in data["items"]] == ["Cocktail Alpha"]

    def test_sparse_dimension_params_repeat_and_widen(self, client, db):
        """``game_format`` (likewise ``cabinet`` and ``production_status``)
        is repeatable on the wire; a Model holds exactly one value, so
        repeated slugs select the union (roll-up semantics pinned in
        ``test_game_rows.py``)."""
        from apps.catalog.tests.game_builders import _model, _title

        t1 = _title("Bingo Hall", "bingo-hall")
        _model(t1, "bingo-hall-m", game_format="bingo")
        t2 = _title("Shuffle Bowl", "shuffle-bowl")
        _model(t2, "shuffle-bowl-m", game_format="shuffle")
        t3 = _title("Plain Pin", "plain-pin")
        _model(t3, "plain-pin-m", game_format="pinball")
        data = client.get("/api/games/?game_format=bingo&game_format=shuffle").json()
        assert {item["name"] for item in data["items"]} == {
            "Bingo Hall",
            "Shuffle Bowl",
        }
        assert data["count"] == 2


class TestEdgeParams:
    """The repeatable ``edge`` param end to end — key, ``:in`` direction and
    the unknown-key matches-nothing rule (roll-up semantics are pinned in
    ``test_game_rows.py``)."""

    @pytest.fixture
    def copied(self, db):
        from apps.catalog.models import LicenseStatus, RelationshipType
        from apps.catalog.tests.game_builders import _edge, _model, _title

        t = _title("Big Valley", "big-valley")
        original = _model(t, "big-valley-bally", name="Big Valley")
        rmg = _model(t, "big-valley-rmg", name="Big Valley (RMG)")
        _edge(
            rmg,
            original,
            RelationshipType.COPY,
            license_status=LicenseStatus.UNLICENSED,
        )

    def test_edge_filters_the_listing(self, client, copied):
        data = client.get("/api/games/?edge=copy").json()
        assert [item["name"] for item in data["items"]] == ["Big Valley (RMG)"]
        assert data["count"] == 1

    def test_edge_inbound_direction(self, client, copied):
        data = client.get("/api/games/?edge=copy:in").json()
        assert [item["name"] for item in data["items"]] == ["Big Valley"]

    def test_unknown_edge_matches_nothing(self, client, copied):
        data = client.get("/api/games/?edge=bogus").json()
        assert data == {"items": [], "count": 0}


class TestGamesFacetsPage:
    def test_payload_shape(self, client, db):
        data = client.get("/api/pages/games").json()
        assert set(data) == {"filter_options", "query_count"}
        assert set(data["filter_options"]) == {
            "manufacturer",
            "person",
            "tech_gen",
            "display_type",
            "system",
            "reward_type",
            "edge",
            "theme",
            "feature",
            "franchise",
            "series",
            "player_count",
        }
        assert data["query_count"] is None

    def test_facet_option_shape(self, client, db, williams_entity):
        t = Title.objects.create(name="Shape", slug="shape")
        make_machine_model(
            name="Shape", slug="shape-m", corporate_entity=williams_entity, title=t
        )
        opts = client.get("/api/pages/games").json()["filter_options"]
        assert opts["manufacturer"] == [
            {"public_id": "williams", "name": "Williams", "count": 1}
        ]

    def test_badge_equals_result_count(self, client, db, williams_entity, stern_entity):
        t = Title.objects.create(name="Mixed", slug="mixed")
        make_machine_model(
            name="Mixed", slug="mixed-w", corporate_entity=williams_entity, title=t
        )
        make_machine_model(
            name="Mixed (B)", slug="mixed-b", corporate_entity=stern_entity, title=t
        )
        opts = client.get("/api/pages/games").json()["filter_options"]
        for o in opts["manufacturer"]:
            count = client.get(f"/api/games/?manufacturer={o['public_id']}").json()[
                "count"
            ]
            assert o["count"] == count, o

    def test_query_count_ignores_active_facets(self, client, db, williams_entity):
        t = Title.objects.create(name="Gated", slug="gated")
        make_machine_model(
            name="Gated", slug="gated-m", corporate_entity=williams_entity, title=t
        )
        # Filtered to a manufacturer that hides the title, q alone still finds it.
        data = client.get("/api/pages/games?q=gated&manufacturer=stern").json()
        assert data["query_count"] == 1

    def test_query_count_sees_model_names(self, client, db, williams_entity):
        """A search that finds a Model must not offer to create a Title: the
        gate shares the listing predicate, Model names included."""
        t = Title.objects.create(name="Rock", slug="rock")
        make_machine_model(name="Rock", slug="rock-m", title=t)
        make_machine_model(
            name="Rock Encore",
            slug="rock-encore",
            corporate_entity=williams_entity,
            title=t,
        )
        assert client.get("/api/pages/games?q=Rock%20Encore").json()["query_count"] == 1
