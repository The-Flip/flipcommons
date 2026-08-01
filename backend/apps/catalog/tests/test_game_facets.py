"""Tests for the card-grain facet fan-out (``apps.catalog.api._game_facets``).

A badge must count the cards its filter click yields: a unanimous Title one, a
shattered Title one per matching Model, an absorbed Variant none. The
manufacturer cases cover the base cell algebra; each further shape
gets the case that distinguishes it — hierarchy ancestor roll-up, player
buckets, and the Title-only vacuity branch including empty Titles — and the
badge == result-count invariant runs across every dimension, which is what
pins all of them to the rows engine at once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace

from apps.catalog.api._game_facets import GameFacetOptions, game_facet_counts
from apps.catalog.api._game_rows import (
    ACCUMULATING_DIMENSIONS,
    MODEL_DIMENSION_SPECS,
    UNCLASSIFIED,
    GameFilters,
    ModelDimension,
    game_rows_merged,
    preset_values,
)
from apps.catalog.engine.query.facet_helpers import FacetOption
from apps.catalog.models import LicenseStatus, RelationshipType
from apps.catalog.tests.game_builders import (
    _edge,
    _franchise,
    _model,
    _series,
    _theme,
    _title,
)


def _mfr_counts(f: GameFilters) -> dict[str, int]:
    return {o.public_id: o.count for o in game_facet_counts(f).manufacturer}


def _counts(options: list[FacetOption]) -> dict[str, int]:
    return {o.public_id: o.count for o in options}


# ---------------------------------------------------------------------------
# Manufacturer — the base cell algebra
# ---------------------------------------------------------------------------


class TestManufacturerFacet:
    def test_unanimous_title_counts_one_card(self, db):
        t = _title("Uniform", "uniform")
        _model(t, "uniform-a", manufacturer="stern")
        _model(t, "uniform-b", manufacturer="stern")
        assert _mfr_counts(GameFilters()) == {"stern": 1}

    def test_shattered_title_counts_matching_models(self, db):
        t = _title("Big Valley", "big-valley")
        _model(t, "bv-bally", manufacturer="bally")
        _model(t, "bv-rmg-1", manufacturer="rmg")
        _model(t, "bv-rmg-2", manufacturer="rmg")
        assert _mfr_counts(GameFilters()) == {"bally": 1, "rmg": 2}

    def test_variant_absorbed_into_matching_parent(self, db):
        t = _title("Godzilla", "godzilla")
        premium = _model(t, "g-premium", manufacturer="stern")
        _model(t, "g-70th", manufacturer="stern", variant_of=premium)
        _model(t, "g-sega", manufacturer="sega")
        # Premium + its Variant collapse to one Stern card.
        assert _mfr_counts(GameFilters()) == {"stern": 1, "sega": 1}

    def test_live_model_under_deleted_title_earns_no_badge(self, db):
        """The facet's sources are guarded like the candidate set: a deleted
        Title's live Model must not tally as a (unanimous!) card."""
        t = _title("Ghost", "ghost")
        _model(t, "ghost-m", manufacturer="stern")
        t.status = "deleted"
        t.save()
        t2 = _title("Real", "real")
        _model(t2, "real-m", manufacturer="bally")
        assert _mfr_counts(GameFilters()) == {"bally": 1}

    def test_own_dimension_is_excluded(self, db):
        t = _title("Big Valley", "big-valley")
        _model(t, "bv-bally", manufacturer="bally")
        _model(t, "bv-rmg", manufacturer="rmg")
        # With manufacturer=rmg active the badge base still counts bally (N-1).
        assert _mfr_counts(GameFilters(manufacturer="rmg")) == {"bally": 1, "rmg": 1}

    def test_selected_value_stays_visible_at_zero(self, db):
        t = _title("Solo", "solo")
        _model(t, "solo-m", manufacturer="stern")
        # A q matching nothing prunes every value; the active selection is
        # re-added at count 0 so the sidebar can still show it deselectable.
        assert _mfr_counts(GameFilters(manufacturer="stern", q="zzz")) == {"stern": 0}


# ---------------------------------------------------------------------------
# Title-only and hierarchical dimensions
# ---------------------------------------------------------------------------


class TestShapes:
    def test_person_shatter_and_rollup(self, db):
        t = _title("Credits", "credits")
        _model(t, "credits-a", persons=("lawlor",))
        _model(t, "credits-b")
        t2 = _title("Both", "both")
        _model(t2, "both-a", persons=("lawlor",))
        _model(t2, "both-b", persons=("lawlor",))
        # One Model card from the shattered Title, one Title card from the
        # unanimous one.
        assert _counts(game_facet_counts(GameFilters()).person) == {"lawlor": 2}

    def test_reward_value_per_model(self, db):
        t = _title("Prizes", "prizes")
        _model(t, "prizes-a", reward_types=("replay", "extra-ball"))
        _model(t, "prizes-b", reward_types=("replay",))
        # replay covers the Title (1 card); extra-ball shatters to one Model.
        assert _counts(game_facet_counts(GameFilters()).reward_type) == {
            "replay": 1,
            "extra-ball": 1,
        }

    def test_theme_ancestor_rollup(self, db):
        sports = _theme("sports")
        _theme("horse-racing", parents=(sports,))
        t = _title("Derby", "derby")
        _model(t, "derby-m", themes=("horse-racing",))
        counts = _counts(game_facet_counts(GameFilters()).theme)
        # The child-tagged Model counts under the parent value too, and the
        # Title is unanimous for both values.
        assert counts == {"horse-racing": 1, "sports": 1}

    def test_feature_partial_tag_shatters(self, db):
        t = _title("Balls", "balls")
        _model(t, "balls-a", features=("multiball",))
        _model(t, "balls-b", name="Balls B")
        assert _counts(game_facet_counts(GameFilters()).gameplay_feature) == {
            "multiball": 1
        }

    def test_player_buckets_fixed_list(self, db):
        t = _title("Crowd", "crowd")
        _model(t, "crowd-7", player_count=7)
        _model(t, "crowd-4", name="Crowd 4", player_count=4)
        buckets = {
            p.value: p.count for p in game_facet_counts(GameFilters()).player_count
        }
        # 7 folds into the 6-or-more bucket; empty buckets stay listed at 0.
        assert buckets == {1: 0, 2: 0, 4: 1, 6: 1}

    def test_franchise_vacuous_counts_titles_including_empty(self, db):
        """With no Model-only dimension active, rung 1 is vacuous: every Title
        carrying the value cards — including one with zero live Models."""
        fr = _franchise("star-wars")
        _title("Empty", "empty", franchise=fr)
        t = _title("Full", "full", franchise=fr)
        _model(t, "full-a", manufacturer="stern")
        _model(t, "full-b", manufacturer="bally")
        assert _counts(game_facet_counts(GameFilters()).franchise) == {"star-wars": 2}

    def test_franchise_under_model_dimension_shatters(self, db):
        fr = _franchise("harley-davidson")
        t = _title("Harley", "harley", franchise=fr)
        _model(t, "harley-sega", manufacturer="sega")
        _model(t, "harley-stern", manufacturer="stern")
        counts = _counts(game_facet_counts(GameFilters(manufacturer="sega")).franchise)
        # Unanimity over manufacturer fails, so the franchise badge counts the
        # one Sega Model card — matching what clicking the franchise shows.
        assert counts == {"harley-davidson": 1}

    def test_franchise_with_q_counts_model_contributions(self, db):
        """The vacuity branch still tallies rung-2 cards: a Title failing its
        own ``q`` contributes its matching Models."""
        fr = _franchise("rock")
        t = _title("Rock", "rock", franchise=fr)
        _model(t, "rock-m", name="Rock")
        _model(t, "rock-encore-m", name="Rock Encore")
        counts = _counts(game_facet_counts(GameFilters(q="Encore")).franchise)
        assert counts == {"rock": 1}


class TestEdgeFacet:
    def test_options_tally_distinct_models_not_edge_rows(self, db):
        """Two copy edges on one Model (different targets) are one matching
        Model, and its two targets each count under the inbound key."""
        t = _title("Sources", "sources")
        a = _model(t, "sources-a", name="Sources A")
        b = _model(t, "sources-b", name="Sources B")
        prolific = _model(t, "sources-prolific", name="Sources Prolific")
        _edge(prolific, a, RelationshipType.COPY)
        _edge(prolific, b, RelationshipType.COPY)
        counts = _counts(game_facet_counts(GameFilters()).edge)
        assert counts == {"copy": 1, "copy:in": 2}

    def test_unanimous_title_counts_one_card(self, db):
        t_orig = _title("Original", "original")
        original = _model(t_orig, "original-m")
        t_copy = _title("Copy Town", "copy-town")
        _edge(_model(t_copy, "copy-town-m"), original, RelationshipType.COPY)
        counts = _counts(game_facet_counts(GameFilters()).edge)
        # The single-Model copy Title rolls up to one card either way round.
        assert counts == {"copy": 1, "copy:in": 1}

    def test_selected_unknown_key_stays_visible_at_zero(self, db):
        t = _title("Solo", "solo")
        _model(t, "solo-m")
        counts = _counts(game_facet_counts(GameFilters(edge=("bogus",))).edge)
        assert counts == {"bogus": 0}


class TestSparseFacet:
    """Null FKs fold into the default value's count; the option list stays
    real vocabulary values only."""

    def _catalog(self) -> None:
        t1 = _title("Plain", "plain")
        _model(t1, "plain-m")  # no format recorded — the default bucket
        t2 = _title("Explicit", "explicit")
        _model(t2, "explicit-m", game_format="pinball")
        t3 = _title("Bingo", "bingo")
        _model(t3, "bingo-m", game_format="bingo-pinball")

    def test_null_folds_into_the_default_count(self, db):
        self._catalog()
        counts = _counts(game_facet_counts(GameFilters()).game_format)
        # The unclassified Model counts under pinball beside the explicit one;
        # there is never an "unclassified" option.
        assert counts == {"pinball": 2, "bingo-pinball": 1}

    def test_mixed_title_shatters_under_each_value(self, db):
        """A Title mixing formats cards one Model under each value, so the
        badges sum to more than the unfiltered listing — union counts aren't
        additive at card grain."""
        t = _title("Mixed", "mixed")
        _model(t, "mixed-pin", game_format="pinball")
        _model(t, "mixed-bingo", name="Mixed Bingo", game_format="bingo-pinball")
        counts = _counts(game_facet_counts(GameFilters()).game_format)
        assert counts == {"pinball": 1, "bingo-pinball": 1}
        assert len(game_rows_merged(GameFilters())) == 1  # one unfiltered card
        preset = preset_values(MODEL_DIMENSION_SPECS["game_format"], "pinball")
        assert len(game_rows_merged(GameFilters(game_format=preset))) == 1
        assert len(game_rows_merged(GameFilters(game_format=("bingo-pinball",)))) == 1

    def test_no_unclassified_option_even_when_selected(self, db):
        """The canonical preset URL always carries UNCLASSIFIED; the payload
        must still offer real vocabulary values only."""
        self._catalog()
        preset = preset_values(MODEL_DIMENSION_SPECS["game_format"], "pinball")
        counts = _counts(game_facet_counts(GameFilters(game_format=preset)).game_format)
        assert UNCLASSIFIED not in counts
        # N-1: the own-dimension selection doesn't narrow its own option list.
        assert counts == {"pinball": 2, "bingo-pinball": 1}

    def test_selected_real_slug_stays_visible_at_zero(self, db):
        self._catalog()
        f = GameFilters(game_format=("bingo-pinball",), q="zzz")
        counts = _counts(game_facet_counts(f).game_format)
        # Name resolution comes from the vocabulary table (standard
        # with_selected), and the pruned selection re-enters at 0.
        assert counts["bingo-pinball"] == 0


class TestAccumulatingDimensions:
    """The multi-select dimensions AND their values, so clicking one adds it to
    what is already chosen. Their badges must predict *that*, not the value on
    its own — the N-1 exclusion that is right for a replacing control promises a
    count the click can't deliver here."""

    def _catalog(self) -> None:
        t1 = _title("Both", "both")
        _model(t1, "both-m", reward_types=("replay", "add-a-ball"))
        t2 = _title("Replay Only", "replay-only")
        _model(t2, "replay-only-m", reward_types=("replay",))
        t3 = _title("Ball Only", "ball-only")
        _model(t3, "ball-only-m", reward_types=("add-a-ball",))

    def test_badge_predicts_the_added_selection(self, db):
        self._catalog()
        f = GameFilters(reward_types=("replay",))
        badge = _counts(game_facet_counts(f).reward_type)["add-a-ball"]
        clicked = len(
            game_rows_merged(GameFilters(reward_types=("replay", "add-a-ball")))
        )
        # Only "Both" carries each of them; "Ball Only" is add-a-ball alone and
        # the active Replay selection excludes it.
        assert (badge, clicked) == (1, 1)

    def test_unselected_dimension_is_unaffected(self, db):
        """With nothing chosen the dimension isn't applied at all, so the base
        is identical either way — which is what keeps the cached no-filter
        payload off the blast radius."""
        self._catalog()
        counts = _counts(game_facet_counts(GameFilters()).reward_type)
        assert counts == {"replay": 2, "add-a-ball": 2}


# ---------------------------------------------------------------------------
# The badge == result-count invariant, across every dimension
# ---------------------------------------------------------------------------

# Facet output field → the ``GameFilters`` field it narrows. The singular →
# plural hops are the existing vocabulary split (the facet payload is singular,
# ``GameFilters`` carries Django's plural M2M names), not typos.
FACET_FILTER_FIELD: dict[str, str] = {
    "manufacturer": "manufacturer",
    "person": "person",
    "technology_generation": "technology_generation",
    "display_type": "display_type",
    "system": "system",
    "reward_type": "reward_types",
    "edge": "edge",
    "cabinet": "cabinet",
    "game_format": "game_format",
    "production_status": "production_status",
    "theme": "themes",
    "gameplay_feature": "gameplay_features",
    "franchise": "franchise",
    "series": "series",
}


def _sparse_click(key: ModelDimension, value: str) -> tuple[str, ...]:
    """A sparse-dimension click: replace semantics through the preset — a
    badge must equal what the UI's click writes, and it writes
    ``preset_values``."""
    return preset_values(MODEL_DIMENSION_SPECS[key], value)


def _add(current: tuple[str, ...], value: str) -> tuple[str, ...]:
    """A click on an accumulating dimension: the value joins the selection.
    Re-clicking a chosen value deselects it in the UI, so it is a no-op here —
    a selected value's badge reports the current result count."""
    return current if value in current else (*current, value)


# How clicking a facet value narrows the ambient filter set. Spelled out rather
# than built from ``FACET_FILTER_FIELD`` because a dynamic ``replace(**{...})``
# is untyped, and this dict is the thing most worth type-checking: modelling
# every click as a *replace* is precisely what hid the multi-select badge bug.
# ``test_multi_dimension_narrowers_accumulate`` is the derived guard over it.
NARROWERS: dict[str, Callable[[GameFilters, str], GameFilters]] = {
    "manufacturer": lambda f, v: replace(f, manufacturer=v),
    "person": lambda f, v: replace(f, person=v),
    "technology_generation": lambda f, v: replace(f, technology_generation=v),
    "display_type": lambda f, v: replace(f, display_type=v),
    "system": lambda f, v: replace(f, system=v),
    "reward_type": lambda f, v: replace(f, reward_types=_add(f.reward_types, v)),
    "edge": lambda f, v: replace(f, edge=_add(f.edge, v)),
    "cabinet": lambda f, v: replace(f, cabinet=_sparse_click("cabinet", v)),
    "game_format": lambda f, v: replace(f, game_format=_sparse_click("game_format", v)),
    "production_status": lambda f, v: replace(
        f, production_status=_sparse_click("production_status", v)
    ),
    "theme": lambda f, v: replace(f, themes=_add(f.themes, v)),
    "gameplay_feature": lambda f, v: replace(
        f, gameplay_features=_add(f.gameplay_features, v)
    ),
    "franchise": lambda f, v: replace(f, franchise=v),
    "series": lambda f, v: replace(f, series=v),
}


def _build_catalog() -> None:
    """A small catalog exercising every shape at once: a shattering Title, a
    Variant, a single-Model Title in a Series, an empty Title in a Franchise,
    a theme hierarchy. ``test_fixture_exercises_every_facet`` pins that every
    dimension gets at least one option out of this — extend it there when a
    dimension is added."""
    liquid = _theme("liquid")
    _theme("water", parents=(liquid,))
    fr = _franchise("alpha-verse")
    t1 = _title("Alpha", "alpha", franchise=fr)
    alpha_stern = _model(
        t1,
        "alpha-stern",
        name="Alpha",
        manufacturer="stern",
        year=1990,
        technology_generation="ss",
        display_type="dmd",
        system="wpc",
        player_count=4,
        themes=("water",),
        features=("multiball",),
        reward_types=("replay",),
        persons=("lawlor",),
        # Alpha mixes formats, so the default-bucket click shatters it.
        game_format="pinball",
    )
    alpha_bally = _model(
        t1,
        "alpha-bally",
        name="Alpha Encore",
        manufacturer="bally",
        year=1991,
        technology_generation="em",
        player_count=2,
        themes=("liquid",),
        features=("ramps",),
        reward_types=("extra-ball",),
        game_format="bingo-pinball",
    )
    t2 = _title("Beta", "beta")
    parent = _model(
        t2,
        "beta-m",
        manufacturer="stern",
        themes=("water",),
        features=("multiball", "ramps"),
        reward_types=("replay", "extra-ball"),
        # Explicit default beside a null: both land in the floor bucket.
        cabinet="floor",
    )
    _model(t2, "beta-le", manufacturer="stern", themes=("water",), variant_of=parent)
    t3 = _title("Gamma", "gamma", series=_series("gamma-saga"))
    gamma = _model(
        t3,
        "gamma-m",
        manufacturer="gottlieb",
        player_count=7,
        features=("multiball",),
        reward_types=("replay",),
        persons=("lawlor",),
        cabinet="cocktail",
        production_status="announced",
    )
    # Gamma bootlegs Alpha's design on converted Alpha Encore cabinets — one
    # Model satisfying two edge keys (plus the composite), the shape that
    # gives the edge facet a second click while a first selection is active.
    _edge(
        gamma,
        alpha_stern,
        RelationshipType.COPY,
        license_status=LicenseStatus.UNLICENSED,
    )
    _edge(gamma, alpha_bally, RelationshipType.CONVERSION)
    _title("Empty", "empty", franchise=fr)


class TestBadgeEqualsResultCount:
    FILTERS = (
        GameFilters(),
        GameFilters(q="Alpha"),
        GameFilters(q="Encore"),
        GameFilters(manufacturer="stern"),
        GameFilters(franchise="alpha-verse"),
        GameFilters(series="gamma-saga"),
        GameFilters(themes=("water",)),
        GameFilters(player_count=4),
        GameFilters(person="lawlor", themes=("liquid",)),
        # One per accumulating dimension, so the loop reaches the second-click
        # path each of them takes.
        GameFilters(gameplay_features=("multiball",)),
        GameFilters(reward_types=("replay",)),
        GameFilters(themes=("liquid",), reward_types=("extra-ball",)),
        GameFilters(edge=("copy",)),
        GameFilters(edge=("bootleg", "conversion")),
        GameFilters(edge=("copy:in",), q="Alpha"),
        # The sparse states: the canonical preset pair, a lone true-null
        # selection, a minority value, and the preset composed with another
        # dimension.
        GameFilters(game_format=("pinball", UNCLASSIFIED)),
        GameFilters(game_format=(UNCLASSIFIED,)),
        GameFilters(cabinet=("cocktail",)),
        GameFilters(production_status=("produced", UNCLASSIFIED), themes=("water",)),
    )

    def test_narrowers_cover_every_facet(self):
        """A facet output field without a narrower would silently drop out of
        the invariant loop — the completeness half a Literal can't prove."""
        field_names = {f.name for f in fields(GameFacetOptions)}
        assert set(FACET_FILTER_FIELD) | {"player_count"} == field_names

    def test_registry_bindings_cover_the_payload(self):
        """The registry is the one place a Model dimension declares its facet;
        pin that the declared facet names are exactly the Model-dimension
        payload fields. Franchise/series are Title-only (no registry entry);
        player_count's bucket assembly is bespoke but its ``BucketFacet``
        still declares the name, so an undeclared payload field fails here."""
        declared = {
            spec.facet.name
            for spec in MODEL_DIMENSION_SPECS.values()
            if spec.facet is not None
        }
        field_names = {f.name for f in fields(GameFacetOptions)}
        assert declared | {"franchise", "series"} == field_names

    def test_facet_filter_field_matches_the_registry(self):
        """The test vocabulary's facet → filter-field mapping must agree with
        the registry — the transposition guard (a facet counted against one
        dimension while its clicks narrow another)."""
        from_registry = {
            spec.facet.name: spec.key
            for spec in MODEL_DIMENSION_SPECS.values()
            if spec.facet is not None and spec.facet.name != "player_count"
        }
        assert {
            **from_registry,
            "franchise": "franchise",
            "series": "series",
        } == FACET_FILTER_FIELD

    def test_every_narrowed_field_exists_on_the_filter_set(self):
        """The singular → plural hop is hand-written, so pin that each target
        names a real field — the mapping the guard below reads."""
        filter_fields = {f.name for f in fields(GameFilters)}
        assert set(FACET_FILTER_FIELD.values()) <= filter_fields
        assert set(FACET_FILTER_FIELD) == set(NARROWERS)

    def test_multi_dimension_narrowers_accumulate(self):
        """Derived from the engine's own arity: every dimension the engine
        treats as accumulating must be *modelled* as accumulating here.

        This guard exists because the miss already happened once: a dimension
        modelled as replacing where the engine accumulates left the invariant
        below never exercising a second selection in that dimension, and a
        badge that promised 6 and delivered 0 passed the whole suite."""
        for facet, field in FACET_FILTER_FIELD.items():
            if field not in ACCUMULATING_DIMENSIONS:
                continue
            after: object = getattr(
                NARROWERS[facet](NARROWERS[facet](GameFilters(), "one"), "two"), field
            )
            assert after == ("one", "two"), facet

    def test_fixture_exercises_every_facet(self, db):
        """A dimension the fixture yields zero options for turns the invariant
        loop into a silent no-op — this guard is what catches a fixture gap
        (it caught ``series`` carrying no coverage at all)."""
        _build_catalog()
        opts = game_facet_counts(GameFilters())
        for facet in NARROWERS:
            assert getattr(opts, facet), facet
        assert any(p.count for p in opts.player_count)

    def test_fixture_offers_a_second_click_per_multi_dimension(self, db):
        """An accumulating dimension only diverges from the N-1 reading once one
        value is chosen, so the loop stays blind to it unless the fixture offers
        a *second* value to click while the first is active."""
        _build_catalog()
        for facet, field in FACET_FILTER_FIELD.items():
            if field not in ACCUMULATING_DIMENSIONS:
                continue
            first = getattr(game_facet_counts(GameFilters()), facet)[0].public_id
            active = NARROWERS[facet](GameFilters(), first)
            assert len(getattr(game_facet_counts(active), facet)) > 1, facet

    def test_every_badge_matches_its_click(self, db):
        _build_catalog()
        for f in self.FILTERS:
            opts = game_facet_counts(f)
            for facet, narrow in NARROWERS.items():
                for o in getattr(opts, facet):
                    got = len(game_rows_merged(narrow(f, o.public_id)))
                    assert o.count == got, (facet, o.public_id, f)
            for p in opts.player_count:
                got = len(game_rows_merged(replace(f, player_count=p.value)))
                assert p.count == got, ("player_count", p.value, f)
