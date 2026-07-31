"""Tests for the card-grain roll-up engine (``apps.catalog.api._game_rows``).

Coverage:

- **The three rungs** — a unanimous Title yields one Title card; a shattered
  Title yields one card per matching Model; a Variant is absorbed when its
  parent matches and surfaces when it does not.
- **The two-set split** — the record-local shared class (``q``) neither breaks
  unanimity (``q=Ice Fever`` / ``q=Karate Fight`` return the Title) nor stops
  gating rung 2 (``q=Ice Fever&theme=X`` returns nothing), and a Title-only
  dimension binds at rung 2 (no Sega Model outside the franchise).
- **Multi-select** — a single Model must carry every selected value.
The facet fan-out at card grain is tested in ``test_game_facets.py``.
"""

from __future__ import annotations

import pytest

from apps.catalog.api._game_rows import (
    MODEL_DIMENSIONS,
    GameFilters,
    GameRow,
    ModelDimension,
    game_rows_merged,
)
from apps.catalog.models import (
    MachineModel,
    ModelAbbreviation,
    Title,
    TitleAbbreviation,
)
from apps.catalog.tests.game_builders import (
    _feature,
    _franchise,
    _model,
    _theme,
    _title,
)


def _rows(f: GameFilters) -> list[GameRow]:
    """The listing rows, in listing order."""
    return game_rows_merged(f)


def _cards(f: GameFilters) -> set[tuple[str, str]]:
    """Order-independent ``(kind, name)`` view for membership assertions."""
    return {(r.kind, r.name) for r in _rows(f)}


# ---------------------------------------------------------------------------
# Rung 1 — unanimity
# ---------------------------------------------------------------------------


class TestRungOne:
    def test_unfiltered_is_all_title_cards(self, db):
        t1 = _title("Solo", "solo")
        _model(t1, "solo-m", manufacturer="stern")
        t2 = _title("Duo", "duo")
        _model(t2, "duo-a", manufacturer="stern")
        _model(t2, "duo-b", manufacturer="bally")
        assert _cards(GameFilters()) == {("title", "Solo"), ("title", "Duo")}

    def test_unanimous_title_rolls_up(self, db):
        t = _title("Uniform", "uniform")
        _model(t, "uniform-a", manufacturer="stern")
        _model(t, "uniform-b", manufacturer="stern")
        f = GameFilters(manufacturer="stern")
        assert _cards(f) == {("title", "Uniform")}

    def test_shattered_title_cards_matching_models(self, db):
        """The VIFICO shape: a copy never rolls up to the Title it shares with
        the original — the matching Models card individually."""
        t = _title("Big Valley", "big-valley")
        _model(t, "big-valley-bally", manufacturer="bally", year=1970)
        _model(t, "big-valley-rmg", name="Big Valley (RMG)", manufacturer="rmg")
        assert _cards(GameFilters(manufacturer="rmg")) == {
            ("model", "Big Valley (RMG)")
        }
        assert _cards(GameFilters(manufacturer="bally")) == {
            ("model", "big-valley-bally")
        }

    def test_deleted_model_neither_breaks_unanimity_nor_cards(self, db):
        t = _title("Half Gone", "half-gone")
        _model(t, "half-gone-live", manufacturer="stern")
        dead = _model(t, "half-gone-dead", manufacturer="bally")
        dead.status = "deleted"
        dead.save()
        assert _cards(GameFilters(manufacturer="stern")) == {("title", "Half Gone")}
        assert _cards(GameFilters(manufacturer="bally")) == set()

    def test_year_is_tested_per_model_and_missing_fails(self, db):
        t = _title("Timed", "timed")
        _model(t, "timed-old", manufacturer="stern", year=1980)
        _model(t, "timed-undated", name="Timed Undated", manufacturer="stern")
        f = GameFilters(year_min=1975, year_max=1985)
        # The undated Model fails the range, so the Title shatters to the dated one.
        assert _cards(f) == {("model", "timed-old")}


# ---------------------------------------------------------------------------
# Lifecycle states — the two the Title-grain listing never had to face
# ---------------------------------------------------------------------------


class TestLifecycleStates:
    def test_live_model_under_deleted_title_never_cards(self, db):
        """restore_model deliberately leaves a deleted parent Title untouched,
        so an active Model under a deleted Title is reachable — and must not
        surface at any rung."""
        t = _title("Ghost", "ghost")
        _model(t, "ghost-m", manufacturer="stern")
        t.status = "deleted"
        t.save()
        assert _cards(GameFilters()) == set()
        assert _cards(GameFilters(manufacturer="stern")) == set()
        assert _cards(GameFilters(q="ghost")) == set()

    def test_empty_title_cards_when_no_model_dimension_active(self, db):
        """An active Title with zero live Models stays listed — unfiltered, by
        its own name and under a Title-only dimension (deleting the last Model
        orphans a Title; the Title-grain API pins this behavior)."""
        fr = _franchise("star-wars")
        _title("Empty", "empty", franchise=fr)
        assert _cards(GameFilters()) == {("title", "Empty")}
        assert _cards(GameFilters(q="empty")) == {("title", "Empty")}
        assert _cards(GameFilters(franchise="star-wars")) == {("title", "Empty")}

    def test_empty_title_hidden_under_model_dimension(self, db):
        """Under an active Model-only dimension, vacuous truth must not card an
        empty Title for a value it never had."""
        _title("Empty", "empty")
        t2 = _title("Full", "full")
        _model(t2, "full-m", manufacturer="stern", year=1990)
        assert _cards(GameFilters(manufacturer="stern")) == {("title", "Full")}
        assert _cards(GameFilters(year_min=1980)) == {("title", "Full")}


# ---------------------------------------------------------------------------
# The dimension-activeness registry
# ---------------------------------------------------------------------------

# One filter set per Model-only dimension, activating exactly that dimension
# with a value nothing in the fixture carries.
ACTIVATING: dict[ModelDimension, GameFilters] = {
    "manufacturer": GameFilters(manufacturer="nobody"),
    "person": GameFilters(person="nobody"),
    "tech_gen": GameFilters(tech_gen="nothing"),
    "display_type": GameFilters(display_type="nothing"),
    "system": GameFilters(system="nothing"),
    "player_count": GameFilters(player_count=2),
    "year": GameFilters(year_min=1990),
    "themes": GameFilters(themes=("nothing",)),
    "features": GameFilters(features=("nothing",)),
    "reward_types": GameFilters(reward_types=("nothing",)),
    "display_subtype": GameFilters(display_subtype="nothing"),
    "tag": GameFilters(tag="nothing"),
    "technology_subgeneration": GameFilters(technology_subgeneration="nothing"),
    "cabinet": GameFilters(cabinet="nothing"),
    "game_format": GameFilters(game_format="nothing"),
    "production_status": GameFilters(production_status="nothing"),
    "corporate_entity": GameFilters(corporate_entity="nothing"),
}


class TestDimensionActivation:
    """Every Model-only dimension must register as active. If the activeness
    registry missed one, rung 1 would skip the unanimity clause and every
    Title would card for a value it never had — a plausible-looking page, not
    an error."""

    def test_every_dimension_has_an_activation_case(self):
        assert set(ACTIVATING) == set(MODEL_DIMENSIONS)

    @pytest.mark.parametrize("key", sorted(ACTIVATING))
    def test_nonmatching_value_returns_nothing(self, db, key):
        t = _title("Plain", "plain")
        _model(t, "plain-m")  # carries no dimension values at all
        assert _cards(ACTIVATING[key]) == set()


# ---------------------------------------------------------------------------
# The record-local shared class (q)
# ---------------------------------------------------------------------------


class TestSharedClass:
    def test_q_does_not_break_unanimity(self, db):
        """``q=Ice Fever`` returns the Title even though the sibling Model is
        named Ice Mania — the shared class never feeds the unanimity count."""
        t = _title("Ice Fever", "ice-fever")
        _model(t, "ice-fever-m", name="Ice Fever")
        _model(t, "ice-mania-m", name="Ice Mania")
        assert _cards(GameFilters(q="Ice Fever")) == {("title", "Ice Fever")}

    def test_q_title_name_beats_model_name(self, db):
        """``q=Karate Fight`` returns the "Black Belt / Karate Fight" Title —
        the query matches the Title's own name, so the Title cards."""
        t = _title("Black Belt / Karate Fight", "black-belt")
        _model(t, "black-belt-m", name="Black Belt", manufacturer="bally")
        _model(t, "karate-fight-m", name="Karate Fight", manufacturer="bally-wulff")
        assert _cards(GameFilters(q="Karate Fight")) == {
            ("title", "Black Belt / Karate Fight")
        }

    def test_q_model_name_cards_the_model(self, db):
        t = _title("Ice Fever", "ice-fever")
        _model(t, "ice-fever-m", name="Ice Fever")
        _model(t, "ice-mania-m", name="Ice Mania")
        assert _cards(GameFilters(q="Ice Mania")) == {("model", "Ice Mania")}

    def test_q_model_abbreviation_cards_the_model(self, db):
        t = _title("Godzilla", "godzilla")
        _model(t, "godzilla-pro", name="Godzilla (Pro)")
        m = _model(t, "godzilla-premium", name="Godzilla (Premium)")
        ModelAbbreviation.objects.create(machine_model=m, value="GZPREM")
        assert _cards(GameFilters(q="gzprem")) == {("model", "Godzilla (Premium)")}

    def test_q_title_abbreviation_cards_the_title(self, db):
        t = _title("Attack from Mars", "afm")
        _model(t, "afm-m", name="Attack from Mars")
        TitleAbbreviation.objects.create(title=t, value="AFM")
        assert _cards(GameFilters(q="afm")) == {("title", "Attack from Mars")}

    def test_q_still_gates_rung_two(self, db):
        """``q=Ice Fever&theme=X`` returns nothing when only the sibling Model
        carries the theme: unanimity fails, and the only theme-carrier fails
        the shared class — ``carding`` is empty."""
        t = _title("Ice Fever", "ice-fever")
        _model(t, "ice-fever-m", name="Ice Fever")
        _model(t, "ice-mania-m", name="Ice Mania", themes=("cold",))
        assert _cards(GameFilters(q="Ice Fever", themes=("cold",))) == set()


# ---------------------------------------------------------------------------
# Rung 2 — Title-only binding
# ---------------------------------------------------------------------------


class TestRungTwo:
    def test_title_only_dimension_binds_models(self, db):
        """``franchise=harley&manufacturer=sega`` returns no Sega Model outside
        the franchise — the binding half of the Title-only class."""
        harley = _franchise("harley-davidson")
        t1 = _title("Harley-Davidson", "harley", franchise=harley)
        _model(t1, "harley-sega", name="Harley (Sega)", manufacturer="sega")
        _model(t1, "harley-stern", name="Harley (Stern)", manufacturer="stern")
        t2 = _title("Golden Poker", "golden-poker")
        _model(t2, "golden-poker-sega", manufacturer="sega")
        f = GameFilters(franchise="harley-davidson", manufacturer="sega")
        assert _cards(f) == {("model", "Harley (Sega)")}

    def test_franchise_alone_rolls_up(self, db):
        harley = _franchise("harley-davidson")
        t = _title("Harley-Davidson", "harley", franchise=harley)
        _model(t, "harley-sega", manufacturer="sega")
        _model(t, "harley-stern", manufacturer="stern")
        f = GameFilters(franchise="harley-davidson")
        # No Model-only dimension → unanimity is vacuous → the Title cards.
        assert _cards(f) == {("title", "Harley-Davidson")}


# ---------------------------------------------------------------------------
# Rung 3 — Variant absorption
# ---------------------------------------------------------------------------


class TestRungThree:
    def _godzilla(self) -> tuple[Title, MachineModel, MachineModel]:
        t = _title("Godzilla", "godzilla")
        premium = _model(t, "godzilla-premium", name="Godzilla (Premium)")
        anniversary = _model(
            t,
            "godzilla-70th",
            name="Godzilla (70th Anniversary)",
            variant_of=premium,
        )
        return t, premium, anniversary

    def test_variant_surfaces_when_parent_fails(self, db):
        _t, _premium, anniversary = self._godzilla()
        anniversary.themes.add(*_model_theme("monster"))
        assert _cards(GameFilters(themes=("monster",))) == {
            ("model", "Godzilla (70th Anniversary)")
        }

    def test_variant_absorbed_when_parent_matches(self, db):
        t, premium, anniversary = self._godzilla()
        # A third Model without the theme keeps the Title from rolling up.
        _model(t, "godzilla-og", name="Godzilla (Sega)")
        theme = _model_theme("monster")
        premium.themes.add(*theme)
        anniversary.themes.add(*theme)
        assert _cards(GameFilters(themes=("monster",))) == {
            ("model", "Godzilla (Premium)")
        }

    def test_variant_absorbed_by_unanimous_title(self, db):
        _t, premium, anniversary = self._godzilla()
        theme = _model_theme("monster")
        premium.themes.add(*theme)
        anniversary.themes.add(*theme)
        assert _cards(GameFilters(themes=("monster",))) == {("title", "Godzilla")}

    def test_variant_named_specifically_cards(self, db):
        _t, _premium, _anniversary = self._godzilla()
        assert _cards(GameFilters(q="70th Anniversary")) == {
            ("model", "Godzilla (70th Anniversary)")
        }


# ---------------------------------------------------------------------------
# Multi-select
# ---------------------------------------------------------------------------


class TestMultiSelect:
    def test_values_split_across_models_do_not_match(self, db):
        """AND across selections lands on a single Model — a Title carrying the
        two themes on two different Models matches neither rung. One Model must
        satisfy every selection; spreading them across siblings is not a
        match."""
        t = _title("Split", "split")
        _model(t, "split-a", themes=("water",))
        _model(t, "split-b", themes=("fire",))
        assert _cards(GameFilters(themes=("water", "fire"))) == set()

    def test_single_model_carrying_both_cards(self, db):
        t = _title("Split", "split")
        _model(t, "split-a", themes=("water",))
        both = _model(t, "split-both", name="Split Both", themes=("water", "fire"))
        assert both.themes.count() == 2
        assert _cards(GameFilters(themes=("water", "fire"))) == {
            ("model", "Split Both")
        }

    def test_parent_theme_matches_descendant_tag(self, db):
        sports = _theme("sports")
        _theme("horse-racing", parents=(sports,))
        t = _title("Derby", "derby")
        _model(t, "derby-m", themes=("horse-racing",))
        assert _cards(GameFilters(themes=("sports",))) == {("title", "Derby")}


# ---------------------------------------------------------------------------
# The rest of the vocabulary — one behavior test per dimension shape
# ---------------------------------------------------------------------------


class TestVocabulary:
    def test_person_shatters_to_the_credited_model(self, db):
        t = _title("Credits", "credits")
        _model(t, "credits-a", name="Credits A", persons=("lawlor",))
        _model(t, "credits-b", name="Credits B")
        assert _cards(GameFilters(person="lawlor")) == {("model", "Credits A")}

    def test_person_rolls_up_when_unanimous(self, db):
        t = _title("Credits", "credits")
        _model(t, "credits-a", persons=("lawlor",))
        _model(t, "credits-b", persons=("lawlor",))
        assert _cards(GameFilters(person="lawlor")) == {("title", "Credits")}

    def test_single_valued_dimensions_land_on_one_model(self, db):
        """Two single-valued dimensions split across sibling Models match
        nothing; carried by one Model they card it — the single-Model rule
        beyond the multi-select dimensions."""
        t = _title("Combo", "combo")
        _model(t, "combo-a", name="Combo A", display_type="dmd", system="wpc")
        _model(t, "combo-b", name="Combo B", display_type="alpha")
        f = GameFilters(display_type="dmd", system="wpc")
        assert _cards(f) == {("model", "Combo A")}
        assert _cards(GameFilters(display_type="alpha", system="wpc")) == set()

    def test_player_bucket_six_means_six_or_more(self, db):
        t = _title("Crowd", "crowd")
        _model(t, "crowd-7", name="Crowd 7", player_count=7)
        _model(t, "crowd-4", name="Crowd 4", player_count=4)
        assert _cards(GameFilters(player_count=6)) == {("model", "Crowd 7")}
        assert _cards(GameFilters(player_count=4)) == {("model", "Crowd 4")}

    def test_parent_feature_matches_descendant_tag(self, db):
        multiball = _feature("multiball")
        _feature("six-ball-multiball", parents=(multiball,))
        t = _title("Balls", "balls")
        _model(t, "balls-m", features=("six-ball-multiball",))
        assert _cards(GameFilters(features=("multiball",))) == {("title", "Balls")}

    def test_reward_types_all_must_land_on_one_model(self, db):
        t = _title("Prizes", "prizes")
        _model(t, "prizes-a", name="Prizes A", reward_types=("replay",))
        _model(t, "prizes-b", name="Prizes B", reward_types=("extra-ball",))
        both = GameFilters(reward_types=("replay", "extra-ball"))
        assert _cards(both) == set()
        _model(
            t,
            "prizes-both",
            name="Prizes Both",
            reward_types=("replay", "extra-ball"),
        )
        assert _cards(both) == {("model", "Prizes Both")}


# ---------------------------------------------------------------------------
# The hidden dimensions — full roll-up semantics, no sidebar, no facets
# ---------------------------------------------------------------------------


class TestHiddenDimensions:
    def test_every_hidden_dimension_narrows_and_rolls_up(self, db):
        """One unanimous Title and one non-carrying Title per dimension: the
        carrying Title rolls up (rung 1 applies to hidden dimensions too), the
        other vanishes."""
        cases: list[tuple[GameFilters, dict[str, object]]] = [
            (GameFilters(display_subtype="hd-lcd"), {"display_subtype": "hd-lcd"}),
            (GameFilters(tag="licensed"), {"tags": ("licensed",)}),
            (GameFilters(cabinet="cocktail"), {"cabinet": "cocktail"}),
            (GameFilters(game_format="bingo"), {"game_format": "bingo"}),
            (
                GameFilters(production_status="announced"),
                {"production_status": "announced"},
            ),
        ]
        for i, (f, kwargs) in enumerate(cases):
            t = _title(f"Carrier {i}", f"carrier-{i}")
            _model(t, f"carrier-{i}-m", **kwargs)  # type: ignore[arg-type]
            other = _title(f"Other {i}", f"other-{i}")
            _model(other, f"other-{i}-m")
            assert _cards(f) == {("title", f"Carrier {i}")}, f

    def test_hidden_dimension_shatters(self, db):
        t = _title("Mixed Formats", "mixed-formats")
        _model(t, "mixed-pin", name="Mixed Pin", game_format="pinball")
        _model(t, "mixed-bingo", name="Mixed Bingo", game_format="bingo")
        assert _cards(GameFilters(game_format="bingo")) == {("model", "Mixed Bingo")}

    def test_sparse_dimension_is_raw_null_never_matches(self, db):
        """PR.SPARSE's default bucket does not exist yet: an unclassified Model
        is not pinball, so only the classified minority cards."""
        t1 = _title("Classified", "classified")
        _model(t1, "classified-m", game_format="pinball")
        t2 = _title("Unclassified", "unclassified")
        _model(t2, "unclassified-m")
        assert _cards(GameFilters(game_format="pinball")) == {("title", "Classified")}

    def test_subgeneration_matches_directly_or_through_system(self, db):
        from apps.catalog.tests.game_builders import _subgen, _system

        t1 = _title("Direct", "direct")
        _model(t1, "direct-m", subgen="mpu")
        t2 = _title("Via System", "via-system")
        sys = _system("wpc-95")
        sys.technology_subgeneration = _subgen("mpu")
        sys.save()
        _model(t2, "via-system-m", system="wpc-95")
        t3 = _title("Neither", "neither")
        _model(t3, "neither-m")
        assert _cards(GameFilters(technology_subgeneration="mpu")) == {
            ("title", "Direct"),
            ("title", "Via System"),
        }

    def test_corporate_entity_is_narrower_than_manufacturer(self, db):
        """Two corporate entities under one manufacturer: the manufacturer
        dimension unifies them, the corporate_entity dimension splits them."""
        from apps.catalog.tests.game_builders import _mfr

        ce_a = _mfr("stern")  # slug stern-ce
        t = _title("Two Plants", "two-plants")
        _model(t, "plant-a", name="Plant A", manufacturer="stern")
        b = _model(t, "plant-b", name="Plant B")
        ce_b = type(ce_a).objects.create(
            slug="stern-second-ce", name="Stern Second", manufacturer=ce_a.manufacturer
        )
        b.corporate_entity = ce_b
        b.save()
        assert _cards(GameFilters(manufacturer="stern")) == {("title", "Two Plants")}
        assert _cards(GameFilters(corporate_entity="stern-ce")) == {
            ("model", "Plant A")
        }
        assert _cards(GameFilters(corporate_entity="stern-second-ce")) == {
            ("model", "Plant B")
        }

    def test_variant_absorption_applies_to_hidden_dimensions(self, db):
        t = _title("Kit", "kit")
        parent = _model(t, "kit-parent", name="Kit Parent", tags=("licensed",))
        _model(
            t,
            "kit-variant",
            name="Kit Variant",
            variant_of=parent,
            tags=("licensed",),
        )
        _model(t, "kit-other", name="Kit Other")
        assert _cards(GameFilters(tag="licensed")) == {("model", "Kit Parent")}


# ---------------------------------------------------------------------------
# Rows: ordering, count, discriminator
# ---------------------------------------------------------------------------


class TestRows:
    def test_ordering_newest_first_nulls_last(self, db):
        t1 = _title("Alpha", "alpha")
        _model(t1, "alpha-m", year=1990)
        t2 = _title("Beta", "beta")
        _model(t2, "beta-m", year=2020)
        t3 = _title("Gamma", "gamma")
        _model(t3, "gamma-m")  # no year → last
        names = [r.name for r in _rows(GameFilters())]
        assert names == ["Beta", "Alpha", "Gamma"]

    def test_kind_carries_the_entity_type_classvars(self, db):
        t = _title("Pair", "pair")
        _model(t, "pair-a", manufacturer="stern")
        _model(t, "pair-b", manufacturer="bally")
        kinds = {r.kind for r in _rows(GameFilters())}
        assert kinds == {Title.entity_type}
        kinds = {r.kind for r in _rows(GameFilters(manufacturer="stern"))}
        assert kinds == {MachineModel.entity_type}


def _model_theme(slug: str):
    """A one-element theme list for ``m.themes.add(*...)`` — reuses the
    get-or-create builder so repeated slugs mean the same Theme row."""
    from apps.catalog.tests.game_builders import _theme

    return [_theme(slug)]
