"""Tests for the server-side title faceting module (``apps.catalog.api._title_facets``).

Coverage:

- **Per-predicate narrowers** — one test per dimension, pinning the three
  non-obvious predicates (first-model manufacturer + the `q` parity trap, year
  range-overlap, player_count `>=6` bucket), multi-value
  AND-of-ORs, descendant-theme/feature expansion, variant exclusion and
  ``.distinct()`` dedup.
- **Facet counts (N-1 rule)** — validated against an *independent naive reference*
  recomputed in plain Python over title "bags" (a brute-force algorithm visibly
  different from the production ``pk__in`` subquery + GROUP BY), so a transcription
  error can't silently match a code bug. Plus the player_count `>=6` divergence
  case the bag fixture deliberately excludes.
- **Ordering** — newest-first with the ``name`` then ``pk`` tie-break.
- **Page endpoint** — ``filter_options``-only shape, the badge == result-count
  invariant, the audience-scoped no-filter cache (hit / miss / invalidate).
- **Query-count guards** — both endpoints' query count is independent of row
  count (catches an N+1 fan-out or a ``list(qs)`` regression).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.api._title_facets import (
    FacetOption,
    FilterOptions,
    TitleFilters,
    facet_counts,
    filtered_titles,
    ordered_titles,
)
from apps.catalog.cache import invalidate_response_cache, titles_facets_key
from apps.catalog.models import (
    CorporateEntity,
    Credit,
    CreditRole,
    DisplayType,
    Franchise,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    Person,
    RewardType,
    Series,
    System,
    TechnologyGeneration,
    Theme,
    Title,
    TitleAbbreviation,
)
from apps.catalog.tests.conftest import make_machine_model

# ---------------------------------------------------------------------------
# Row builders — create real catalog rows without running the resolver.
# All taxonomy helpers get_or_create by slug so the same slug across rows
# refers to the same value (the whole point of a facet).
# ---------------------------------------------------------------------------


def _mfr(slug: str) -> CorporateEntity:
    """A CorporateEntity whose manufacturer slug is *slug* (the facet value)."""
    mfr, _ = Manufacturer.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    ce, _ = CorporateEntity.objects.get_or_create(
        slug=f"{slug}-ce",
        defaults={"name": mfr.name, "manufacturer": mfr},
    )
    return ce


def _tech(slug: str) -> TechnologyGeneration:
    obj, _ = TechnologyGeneration.objects.get_or_create(
        slug=slug, defaults={"name": slug.upper()}
    )
    return obj


def _display(slug: str) -> DisplayType:
    obj, _ = DisplayType.objects.get_or_create(
        slug=slug, defaults={"name": slug.upper()}
    )
    return obj


def _system(slug: str) -> System:
    sys_mfr, _ = Manufacturer.objects.get_or_create(
        slug="system-manufacturer", defaults={"name": "System Manufacturer"}
    )
    obj, _ = System.objects.get_or_create(
        slug=slug, defaults={"name": slug.upper(), "manufacturer": sys_mfr}
    )
    return obj


def _theme(slug: str, *, parents: tuple[Theme, ...] = ()) -> Theme:
    obj, _ = Theme.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    for p in parents:
        obj.parents.add(p)
    return obj


def _feature(
    slug: str, *, parents: tuple[GameplayFeature, ...] = ()
) -> GameplayFeature:
    obj, _ = GameplayFeature.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    for p in parents:
        obj.parents.add(p)
    return obj


def _reward(slug: str) -> RewardType:
    obj, _ = RewardType.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _person(slug: str) -> Person:
    obj, _ = Person.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _role() -> CreditRole:
    obj, _ = CreditRole.objects.get_or_create(
        slug="design", defaults={"name": "Design", "display_order": 10}
    )
    return obj


def _franchise(slug: str) -> Franchise:
    obj, _ = Franchise.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _series(slug: str) -> Series:
    obj, _ = Series.objects.get_or_create(
        slug=slug, defaults={"name": slug.replace("-", " ").title()}
    )
    return obj


def _title(name: str, slug: str, **kwargs: object) -> Title:
    return Title.objects.create(name=name, slug=slug, **kwargs)


def _model(
    title: Title,
    slug: str,
    *,
    name: str | None = None,
    manufacturer: str | None = None,
    year: int | None = None,
    tech_gen: str | None = None,
    display_type: str | None = None,
    system: str | None = None,
    player_count: int | None = None,
    themes: tuple[str, ...] = (),
    features: tuple[str, ...] = (),
    reward_types: tuple[str, ...] = (),
    persons: tuple[str, ...] = (),
    variant_of: MachineModel | None = None,
) -> MachineModel:
    m = make_machine_model(
        title=title,
        name=name or slug,
        slug=slug,
        corporate_entity=_mfr(manufacturer) if manufacturer else None,
        year=year,
        technology_generation=_tech(tech_gen) if tech_gen else None,
        display_type=_display(display_type) if display_type else None,
        system=_system(system) if system else None,
        player_count=player_count,
        variant_of=variant_of,
    )
    for s in themes:
        m.themes.add(_theme(s))
    for s in features:
        m.gameplay_features.add(_feature(s))
    for s in reward_types:
        m.reward_types.add(_reward(s))
    for s in persons:
        Credit.objects.create(model=m, person=_person(s), role=_role())
    return m


def _slugs(f: TitleFilters) -> set[str]:
    """The slug set of titles matching *f* (order-independent)."""
    return set(filtered_titles(f).values_list("slug", flat=True))


@pytest.fixture
def _clear_cache():
    """Isolate tests that exercise the facet cache (applied via ``usefixtures``)."""
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Per-dimension predicate tests
# ---------------------------------------------------------------------------


class TestPredicates:
    def test_manufacturer_is_first_model_only(self, db):
        """The manufacturer predicate matches a title's *first* (earliest)
        model's manufacturer — not any model's. A later Williams reissue under a
        Bally original is a Bally title."""
        t = _title("Reissued", "reissued")
        _model(t, "reissued-orig", manufacturer="bally", year=1980)
        _model(t, "reissued-remake", manufacturer="williams", year=2015)

        assert _slugs(TitleFilters(manufacturer="bally")) == {"reissued"}
        assert _slugs(TitleFilters(manufacturer="williams")) == set()

    def test_q_matches_name(self, db):
        _title("Medieval Madness", "mm")
        _model(_title("Other", "other"), "other-m")
        assert _slugs(TitleFilters(q="medieval")) == {"mm"}
        assert _slugs(TitleFilters(q="nope")) == set()

    def test_q_matches_abbreviation(self, db):
        t = _title("Attack from Mars", "afm")
        TitleAbbreviation.objects.create(title=t, value="AFM")
        assert _slugs(TitleFilters(q="afm")) == {"afm"}

    def test_q_matches_first_model_manufacturer_not_later_models(self, db):
        """`q` on a manufacturer name hits the first model's manufacturer only —
        the same invariant as the manufacturer facet (no second-model leakage)."""
        hit = _title("Foo", "foo")
        _model(hit, "foo-m", manufacturer="gottlieb", year=1975)

        miss = _title("Bar", "bar")
        _model(miss, "bar-orig", manufacturer="bally", year=1980)
        _model(miss, "bar-remake", manufacturer="williams", year=2015)

        assert _slugs(TitleFilters(q="gottlieb")) == {"foo"}
        # "williams" only appears as Bar's *second* model → not a manufacturer hit.
        assert _slugs(TitleFilters(q="williams")) == set()

    def test_whitespace_q_is_no_filter(self, db):
        """A whitespace-only ``q`` is treated as no filter (returns all active) —
        agreeing with ``_query_only_count`` (which returns ``None``) rather than
        running a near-whole-catalog ``icontains " "`` (matches manufacturers)."""
        _model(_title("Medieval Madness", "mm"), "mm-m")
        _model(_title("Other", "other"), "other-m")
        assert _slugs(TitleFilters(q="   ")) == {"mm", "other"}

    def test_surrounding_spaces_trimmed(self, db):
        """Surrounding spaces are trimmed at the boundary so they don't leak into
        the match (``q=" medieval "`` matches "Medieval Madness")."""
        _model(_title("Medieval Madness", "mm"), "mm-m")
        assert _slugs(TitleFilters(q="  medieval  ")) == {"mm"}

    def test_person(self, db):
        t = _title("Credited", "credited")
        _model(t, "credited-m", persons=("pat-lawlor",))
        _model(_title("Uncredited", "uncredited"), "uncredited-m")
        assert _slugs(TitleFilters(person="pat-lawlor")) == {"credited"}

    def test_tech_gen(self, db):
        _model(_title("SS", "ss-title"), "ss-m", tech_gen="solid-state")
        _model(_title("EM", "em-title"), "em-m", tech_gen="electromechanical")
        assert _slugs(TitleFilters(tech_gen="solid-state")) == {"ss-title"}

    def test_display_type(self, db):
        _model(_title("Dmd", "dmd-title"), "dmd-m", display_type="dmd")
        _model(_title("Lcd", "lcd-title"), "lcd-m", display_type="lcd")
        assert _slugs(TitleFilters(display_type="dmd")) == {"dmd-title"}

    def test_system(self, db):
        _model(_title("Wpc", "wpc-title"), "wpc-m", system="wpc-95")
        _model(_title("Spike", "spike-title"), "spike-m", system="spike")
        assert _slugs(TitleFilters(system="wpc-95")) == {"wpc-title"}

    def test_franchise(self, db):
        fr = _franchise("star-wars")
        _model(_title("SW Pin", "sw-pin", franchise=fr), "sw-pin-m")
        _model(_title("No FR", "no-fr"), "no-fr-m")
        assert _slugs(TitleFilters(franchise="star-wars")) == {"sw-pin"}

    def test_series(self, db):
        sr = _series("pin-2000")
        _model(_title("RFM", "rfm", series=sr), "rfm-m")
        _model(_title("No SR", "no-sr"), "no-sr-m")
        assert _slugs(TitleFilters(series="pin-2000")) == {"rfm"}

    def test_player_count_exact(self, db):
        _model(_title("Two", "two"), "two-m", player_count=2)
        _model(_title("Four", "four"), "four-m", player_count=4)
        assert _slugs(TitleFilters(player_count=4)) == {"four"}
        assert _slugs(TitleFilters(player_count=2)) == {"two"}

    def test_player_count_six_plus_bucket(self, db):
        """The `6` bucket means "6 or more"."""
        _model(_title("Six", "six"), "six-m", player_count=6)
        _model(_title("Eight", "eight"), "eight-m", player_count=8)
        _model(_title("Four", "four"), "four-m", player_count=4)
        assert _slugs(TitleFilters(player_count=6)) == {"six", "eight"}

    def test_year_range_overlap(self, db):
        """Range OVERLAP: a title matches if any model year falls in the window
        (a multi-model title's [min,max] overlapping the filter [ymin,ymax])."""
        spanning = _title("Spanning", "spanning")
        _model(spanning, "spanning-a", year=1990)
        _model(spanning, "spanning-b", year=2010)  # window 2000-2005 is inside the span
        _model(_title("Early", "early"), "early-m", year=1985)
        _model(_title("Late", "late"), "late-m", year=2020)

        assert _slugs(TitleFilters(year_min=2000, year_max=2005)) == {"spanning"}
        assert _slugs(TitleFilters(year_min=1980, year_max=1986)) == {"early"}
        assert _slugs(TitleFilters(year_min=1980)) == {
            "spanning",
            "early",
            "late",
        }
        assert _slugs(TitleFilters(year_max=1986)) == {"early"}

    def test_themes_multi_value_and_of_ors(self, db):
        """Each selected theme must match (AND); a theme matches if any model
        carries it (OR across models)."""
        both = _title("Both", "both")
        _model(both, "both-a", themes=("horror",))
        _model(both, "both-b", themes=("sci-fi",))  # OR across models
        one = _title("One", "one")
        _model(one, "one-m", themes=("horror",))
        assert _slugs(TitleFilters(themes=("horror", "sci-fi"))) == {"both"}
        assert _slugs(TitleFilters(themes=("horror",))) == {"both", "one"}

    def test_themes_descendant_expansion(self, db):
        """Filtering by a parent theme matches titles tagged only with a child."""
        sports = _theme("sports")
        _theme("air-racing", parents=(sports,))
        t = _title("Child Tagged", "child-tagged")
        _model(t, "child-m", themes=("air-racing",))
        assert _slugs(TitleFilters(themes=("sports",))) == {"child-tagged"}
        assert _slugs(TitleFilters(themes=("air-racing",))) == {"child-tagged"}

    def test_features_multi_value_and_descendant_expansion(self, db):
        physical = _feature("physical")
        _feature("ramp", parents=(physical,))
        t = _title("Ramped", "ramped")
        _model(t, "ramped-m", features=("ramp", "multiball"))
        assert _slugs(TitleFilters(features=("physical",))) == {"ramped"}
        assert _slugs(TitleFilters(features=("ramp", "multiball"))) == {"ramped"}
        assert _slugs(TitleFilters(features=("ramp", "nonexistent"))) == set()

    def test_reward_types_multi_value(self, db):
        t = _title("Rewarded", "rewarded")
        _model(t, "rewarded-m", reward_types=("replay", "extra-ball"))
        _model(
            _title("OneReward", "one-reward"), "one-reward-m", reward_types=("replay",)
        )
        assert _slugs(TitleFilters(reward_types=("replay",))) == {
            "rewarded",
            "one-reward",
        }
        assert _slugs(TitleFilters(reward_types=("replay", "extra-ball"))) == {
            "rewarded"
        }

    def test_variant_models_do_not_satisfy_filters(self, db):
        """A variant (or retired) model can't satisfy a model-level filter."""
        t = _title("Variant Host", "variant-host")
        parent = _model(t, "vh-parent", system="wpc-95")
        _model(t, "vh-variant", system="spike", variant_of=parent)
        assert _slugs(TitleFilters(system="wpc-95")) == {"variant-host"}
        # The variant's system must not leak the title into the spike result set.
        assert _slugs(TitleFilters(system="spike")) == set()

    def test_distinct_dedup(self, db):
        """A title with two models both matching one dimension appears once."""
        t = _title("Twin", "twin")
        _model(t, "twin-a", system="wpc-95")
        _model(t, "twin-b", system="wpc-95")
        assert list(filtered_titles(TitleFilters(system="wpc-95"))) == [t]

    def test_combined_filters_and_across_dimensions(self, db):
        match = _title("Match", "match")
        _model(
            match, "match-m", manufacturer="williams", system="wpc-95", player_count=4
        )
        wrong_system = _title("WrongSystem", "wrong-system")
        _model(wrong_system, "ws-m", manufacturer="williams", system="spike")
        f = TitleFilters(manufacturer="williams", system="wpc-95", player_count=4)
        assert _slugs(f) == {"match"}

    def test_empty_result(self, db):
        _model(_title("Solo", "solo"), "solo-m", manufacturer="williams")
        assert _slugs(TitleFilters(manufacturer="nonexistent")) == set()

    def test_no_filter_returns_all_active(self, db):
        _model(_title("A", "a"), "a-m")
        _model(_title("B", "b"), "b-m")
        assert _slugs(TitleFilters()) == {"a", "b"}


# ---------------------------------------------------------------------------
# Ordering — newest first, name then pk tie-break
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_newest_first_with_name_then_pk_tiebreak(self, db):
        # No-model title sorts last (latest_year NULL).
        _title("No Models", "no-models")
        # Two titles share latest_year 2000 → name asc, then pk asc.
        zebra = _title("Zebra", "zebra")
        _model(zebra, "zebra-m", year=2000)
        apple = _title("Apple", "apple")
        _model(apple, "apple-m", year=2000)
        # Same year AND same name as apple → pk tie-break (apple created first).
        apple_dup = _title("Apple", "apple-dup")
        _model(apple_dup, "apple-dup-m", year=2000)
        # Newest overall.
        newest = _title("Newest", "newest")
        _model(newest, "newest-m", year=2020)

        order = list(ordered_titles(TitleFilters()).values_list("slug", flat=True))
        assert order == [
            "newest",  # 2020
            "apple",  # 2000, name "Apple", lower pk
            "apple-dup",  # 2000, name "Apple", higher pk
            "zebra",  # 2000, name "Zebra"
            "no-models",  # NULL year, last
        ]


# ---------------------------------------------------------------------------
# Facet counts — independent naive reference (parity without re-running prod code)
# ---------------------------------------------------------------------------


class _Row(TypedDict, total=False):
    """One single-model parity title (the single source for both DB rows and the
    naive reference). ``slug``/``name`` are always set; the rest are optional."""

    slug: str
    name: str
    manufacturer: str
    system: str
    display_type: str
    tech_gen: str
    player_count: int
    year: int
    franchise: str
    series: str
    themes: tuple[str, ...]
    features: tuple[str, ...]
    reward_types: tuple[str, ...]
    persons: tuple[str, ...]


# Single-model titles only: each title's facet "bag" *is* its one model, so the
# bag aggregation is trivially correct and the test exercises the N-1 counting
# wiring, not the aggregation. Hierarchy is flat (no parents) so the server's
# ancestor rollup is a no-op here — descendant rollup has its own test above.
# No title has two distinct >=6 player counts (impossible with one model), so the
# documented player_count divergence can't appear and client==server holds.
_PARITY_ROWS: tuple[_Row, ...] = (
    {
        "slug": "p-aa",
        "name": "AA",
        "manufacturer": "mfr-1",
        "system": "sys-a",
        "display_type": "dmd",
        "tech_gen": "ss",
        "player_count": 4,
        "year": 1995,
        "franchise": "fr-1",
        "series": "sr-1",
        "themes": ("theme-x", "theme-y"),
        "features": ("feat-1",),
        "reward_types": ("rt-1",),
        "persons": ("per-1",),
    },
    {
        "slug": "p-bb",
        "name": "BB",
        "manufacturer": "mfr-1",
        "system": "sys-a",
        "display_type": "lcd",
        "tech_gen": "ss",
        "player_count": 2,
        "year": 2001,
        "themes": ("theme-x",),
        "reward_types": ("rt-1",),
        "persons": ("per-2",),
    },
    {
        "slug": "p-cc",
        "name": "CC",
        "manufacturer": "mfr-2",
        "system": "sys-a",
        "display_type": "dmd",
        "tech_gen": "em",
        "player_count": 4,
        "year": 1980,
        "themes": ("theme-x",),
        "persons": ("per-1",),
    },
    {
        "slug": "p-dd",
        "name": "DD",
        "manufacturer": "mfr-1",
        "system": "sys-b",
        "display_type": "dmd",
        "tech_gen": "ss",
        "player_count": 4,
        "year": 1999,
        "themes": ("theme-x", "theme-z"),
        "franchise": "fr-1",
        "persons": ("per-1", "per-2"),
    },
    {
        "slug": "p-ee",
        "name": "EE",
        "manufacturer": "mfr-2",
        "system": "sys-a",
        "display_type": "lcd",
        "tech_gen": "ss",
        "player_count": 8,
        "year": 2010,
        "themes": ("theme-y",),
        "reward_types": ("rt-2",),
    },
    {
        "slug": "p-ff",
        "name": "FF",
        "manufacturer": "mfr-1",
        "system": "sys-a",
        "display_type": "dmd",
        "tech_gen": "ss",
        "player_count": 4,
        "year": 1990,
        "themes": ("theme-x",),
        "series": "sr-1",
        "persons": ("per-1",),
    },
    {
        "slug": "p-gg",
        "name": "GG",
        "manufacturer": "mfr-3",
        "system": "sys-c",
        "display_type": "seg",
        "tech_gen": "em",
        "player_count": 6,
        "year": 1975,
        "themes": ("theme-w",),
    },
    {
        "slug": "p-hh",
        "name": "HH",
        "manufacturer": "mfr-1",
        "system": "sys-a",
        "display_type": "dmd",
        "tech_gen": "ss",
        "player_count": 4,
        "year": 2005,
        "themes": ("theme-x",),
        "reward_types": ("rt-1",),
        "persons": ("per-2",),
    },
)


@dataclass(frozen=True)
class _Bag:
    """A title's facet value-sets — the naive reference's working representation.
    Scalar facets are 0-or-1-element sets so every counted dimension is uniform."""

    manufacturer: frozenset[str]
    tech_gen: frozenset[str]
    display_type: frozenset[str]
    system: frozenset[str]
    person: frozenset[str]
    theme: frozenset[str]
    feature: frozenset[str]
    reward_type: frozenset[str]
    franchise: frozenset[str]
    series: frozenset[str]
    player_count: frozenset[int]
    year: int | None


# Counted facets (the FilterOptions value-list fields). Year is a range bound,
# not a counted option, so it's excluded from the parity comparison.
_COUNTED: tuple[str, ...] = (
    "manufacturer",
    "tech_gen",
    "display_type",
    "system",
    "person",
    "theme",
    "feature",
    "reward_type",
    "franchise",
    "series",
    "player_count",
)


def _one(value: str | None) -> frozenset[str]:
    return frozenset({value}) if value else frozenset()


def _bag(row: _Row) -> _Bag:
    pc = row.get("player_count")
    return _Bag(
        manufacturer=_one(row.get("manufacturer")),
        tech_gen=_one(row.get("tech_gen")),
        display_type=_one(row.get("display_type")),
        system=_one(row.get("system")),
        person=frozenset(row.get("persons", ())),
        theme=frozenset(row.get("themes", ())),
        feature=frozenset(row.get("features", ())),
        reward_type=frozenset(row.get("reward_types", ())),
        franchise=_one(row.get("franchise")),
        series=_one(row.get("series")),
        player_count=frozenset({pc}) if pc is not None else frozenset(),
        year=row.get("year"),
    )


def _dim_values(bag: _Bag, dim: str) -> frozenset[object]:
    """The bag's values for counted dimension *dim* (the tally keys)."""
    sets: dict[str, frozenset[object]] = {
        "manufacturer": bag.manufacturer,
        "tech_gen": bag.tech_gen,
        "display_type": bag.display_type,
        "system": bag.system,
        "person": bag.person,
        "theme": bag.theme,
        "feature": bag.feature,
        "reward_type": bag.reward_type,
        "franchise": bag.franchise,
        "series": bag.series,
        "player_count": frozenset(6 if p >= 6 else p for p in bag.player_count),
    }
    return sets[dim]


def _dim_matches(bag: _Bag, dim: str, f: TitleFilters) -> bool:
    """Does *bag* satisfy the filter for counted dimension *dim*? (Inactive → True.)"""
    scalar: dict[str, str | None] = {
        "manufacturer": f.manufacturer,
        "tech_gen": f.tech_gen,
        "display_type": f.display_type,
        "system": f.system,
        "person": f.person,
        "franchise": f.franchise,
        "series": f.series,
    }
    if dim in scalar:
        want = scalar[dim]
        return want is None or want in _dim_values(bag, dim)
    if dim == "theme":
        return set(f.themes) <= bag.theme
    if dim == "feature":
        return set(f.features) <= bag.feature
    if dim == "reward_type":
        return set(f.reward_types) <= bag.reward_type
    if dim == "player_count":
        if f.player_count is None:
            return True
        if f.player_count >= 6:
            return any(p >= 6 for p in bag.player_count)
        return f.player_count in bag.player_count
    raise AssertionError(dim)


def _always_matches(bag: _Bag, f: TitleFilters) -> bool:
    """Range/`q` predicates that gate *every* counted facet (never the excluded
    dim among the eleven). `q` is left inactive in the parity states."""
    if f.year_min is not None and (bag.year is None or bag.year < f.year_min):
        return False
    return not (f.year_max is not None and (bag.year is None or bag.year > f.year_max))


def _naive_counts(bags: list[_Bag], f: TitleFilters) -> dict[str, dict[object, int]]:
    """Brute-force N-1 counts: for each counted dimension D, count each value of
    D over bags passing every *other* counted filter plus the always-filters."""
    out: dict[str, dict[object, int]] = {}
    for dim in _COUNTED:
        others = [d for d in _COUNTED if d != dim]
        tally: dict[object, int] = {}
        for bag in bags:
            if not _always_matches(bag, f):
                continue
            if not all(_dim_matches(bag, d, f) for d in others):
                continue
            for val in _dim_values(bag, dim):
                tally[val] = tally.get(val, 0) + 1
        out[dim] = tally
    return out


def _facet_dict(options: list[FacetOption]) -> dict[object, int]:
    return {o.public_id: o.count for o in options if o.count}


def _server_counts(opts: FilterOptions) -> dict[str, dict[object, int]]:
    """FilterOptions → ``{dim: {value: count}}`` (count-0 values pruned, matching
    the naive map where absent == zero)."""
    return {
        "manufacturer": _facet_dict(opts.manufacturer),
        "tech_gen": _facet_dict(opts.tech_gen),
        "display_type": _facet_dict(opts.display_type),
        "system": _facet_dict(opts.system),
        "person": _facet_dict(opts.person),
        "theme": _facet_dict(opts.theme),
        "feature": _facet_dict(opts.feature),
        "reward_type": _facet_dict(opts.reward_type),
        "franchise": _facet_dict(opts.franchise),
        "series": _facet_dict(opts.series),
        "player_count": {p.value: p.count for p in opts.player_count if p.count},
    }


@pytest.fixture
def parity_catalog(db):
    """Load the single-source parity fixture into the DB."""
    for row in _PARITY_ROWS:
        title = _title(row["name"], row["slug"])
        franchise = row.get("franchise")
        if franchise:
            title.franchise = _franchise(franchise)
            title.save()
        series = row.get("series")
        if series:
            title.series = _series(series)
            title.save()
        _model(
            title,
            f"{row['slug']}-m",
            name=row["name"],
            manufacturer=row.get("manufacturer"),
            year=row.get("year"),
            tech_gen=row.get("tech_gen"),
            display_type=row.get("display_type"),
            system=row.get("system"),
            player_count=row.get("player_count"),
            themes=row.get("themes", ()),
            features=row.get("features", ()),
            reward_types=row.get("reward_types", ()),
            persons=row.get("persons", ()),
        )


class TestFacetCountParity:
    @pytest.mark.parametrize(
        "f",
        [
            pytest.param(TitleFilters(), id="no-filter"),
            pytest.param(TitleFilters(system="sys-a"), id="single-dim"),
            pytest.param(
                TitleFilters(
                    system="sys-a",
                    themes=("theme-x",),
                    manufacturer="mfr-1",
                    player_count=4,
                ),
                id="multi-dim",
            ),
            pytest.param(
                TitleFilters(manufacturer="mfr-1", year_min=1996, year_max=2006),
                id="with-year-range",
            ),
        ],
    )
    def test_facet_counts_match_naive_reference(self, parity_catalog, f):
        bags = [_bag(row) for row in _PARITY_ROWS]
        assert _server_counts(facet_counts(f)) == _naive_counts(bags, f)

    def test_player_count_six_plus_counts_distinct_titles(self, db):
        """The documented divergence from the client: a title with a 6- and an
        8-player model is counted ONCE in the `6+` bucket (distinct titles —
        badge == result count), where the client's badge double-counts."""
        t = _title("Multi", "multi")
        _model(t, "multi-six", player_count=6)
        _model(t, "multi-eight", player_count=8)
        opts = facet_counts(TitleFilters())
        by_bucket = {p.value: p.count for p in opts.player_count}
        assert by_bucket[6] == 1  # one distinct title, not two models

    def test_count_zero_values_are_pruned(self, parity_catalog):
        """A facet value with no matching titles isn't returned (value-pruning is
        the same GROUP BY as the count)."""
        # mfr-3 (GG) is from 1975; filtering year_min=1980 prunes it everywhere.
        opts = facet_counts(TitleFilters(year_min=1980))
        assert "mfr-3" not in {o.public_id for o in opts.manufacturer}


class TestSelectedValuesStayVisible:
    """A *selected* facet value pruned to count 0 (its combined filters yield no
    matching titles) must stay in its option list with count 0 — otherwise the
    sidebar can't render it deselectable and the active-filter chip can't resolve
    its display name, degrading to the raw slug. Unselected count-0 values stay
    pruned (see ``test_count_zero_values_are_pruned``)."""

    @staticmethod
    def _split_catalog() -> None:
        # Williams made only a horror title; Bally made only a sci-fi title — so
        # any cross pairing (williams+sci-fi, bally+horror) matches no title.
        w = _title("Wms", "wms")
        _model(w, "wms-m", manufacturer="williams", themes=("horror",))
        b = _title("Bly", "bly")
        _model(b, "bly-m", manufacturer="bally", themes=("sci-fi",))

    def test_selected_single_value_pruned_to_zero_is_kept(self, db):
        self._split_catalog()
        f = TitleFilters(manufacturer="williams", themes=("sci-fi",))
        assert not _slugs(f)  # empty result set

        by_slug = {o.public_id: o for o in facet_counts(f).manufacturer}
        assert "williams" in by_slug
        assert by_slug["williams"].count == 0
        assert by_slug["williams"].name == "Williams"  # real name, not the slug

    def test_selected_multi_value_pruned_to_zero_is_kept(self, db):
        self._split_catalog()
        f = TitleFilters(manufacturer="bally", themes=("horror",))
        assert not _slugs(f)  # empty result set

        by_slug = {o.public_id: o for o in facet_counts(f).theme}
        assert "horror" in by_slug
        assert by_slug["horror"].count == 0
        assert by_slug["horror"].name == "Horror"

    def test_present_selected_value_keeps_real_count_and_is_not_duplicated(self, db):
        w1 = _title("Wms1", "wms1")
        _model(w1, "wms1-m", manufacturer="williams")
        w2 = _title("Wms2", "wms2")
        _model(w2, "wms2-m", manufacturer="williams")

        opts = facet_counts(TitleFilters(manufacturer="williams")).manufacturer
        williams = [o for o in opts if o.public_id == "williams"]
        assert len(williams) == 1  # sticky must not duplicate a present value
        assert williams[0].count == 2  # nor clobber its real count to 0


# ---------------------------------------------------------------------------
# Page endpoint — shape, badge==count, cache
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_clear_cache")
class TestPageEndpoint:
    def test_returns_filter_options_only_with_public_id_name_count(self, client, db):
        _model(
            _title("Solo", "solo"), "solo-m", manufacturer="williams", system="wpc-95"
        )
        resp = client.get("/api/pages/titles")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"filter_options", "query_count"}  # no items
        opts = body["filter_options"]
        mfr = opts["manufacturer"]
        assert mfr  # williams present
        assert set(mfr[0]) == {"public_id", "name", "count"}
        assert mfr[0]["public_id"] == "williams"
        assert mfr[0]["count"] == 1
        # Range dims are bounds, not value lists.
        assert set(opts["year"]) == {"min", "max"}

    def test_badge_equals_result_count_for_single_filter(self, client, db):
        """A facet value's count (with no other filter active) equals the number
        of titles `/api/titles/` returns for that value alone."""
        for i in range(3):
            _model(_title(f"W{i}", f"w{i}"), f"w{i}-m", manufacturer="williams")
        for i in range(2):
            _model(_title(f"S{i}", f"s{i}"), f"s{i}-m", manufacturer="stern")

        facets = client.get("/api/pages/titles").json()["filter_options"]
        williams = next(
            o for o in facets["manufacturer"] if o["public_id"] == "williams"
        )
        result_count = client.get("/api/titles/?manufacturer=williams").json()["count"]
        assert williams["count"] == result_count == 3

    def test_no_filter_response_is_cached(self, client, db):
        _model(_title("Cached", "cached"), "cached-m", manufacturer="williams")

        with CaptureQueriesContext(connection) as miss:
            first = client.get("/api/pages/titles")
        with CaptureQueriesContext(connection) as hit:
            second = client.get("/api/pages/titles")

        assert first.json() == second.json()
        assert first["ETag"] == second["ETag"]
        # The hit serves bytes from cache — far fewer queries than the fan-out.
        assert len(hit) < len(miss)

    def test_filtered_response_is_not_cached(self, client, db):
        """Only the no-filter payload is cached; a filtered request must recompute
        so it can't be poisoned by — or poison — the no-filter slot."""
        _model(_title("F", "f"), "f-m", manufacturer="williams")
        client.get("/api/pages/titles?manufacturer=williams")
        # Nothing was written to the no-filter cache key by the filtered request.
        assert cache.get(titles_facets_key()) is None

    def test_cache_invalidates_on_catalog_change(self, client, db):
        _model(_title("First", "first"), "first-m", manufacturer="williams")
        before = client.get("/api/pages/titles").json()["filter_options"]
        assert {o["public_id"] for o in before["manufacturer"]} == {"williams"}

        # A catalog edit adds a new manufacturer and busts the cache.
        _model(_title("Second", "second"), "second-m", manufacturer="stern")
        invalidate_response_cache()

        after = client.get("/api/pages/titles").json()["filter_options"]
        assert {o["public_id"] for o in after["manufacturer"]} == {"williams", "stern"}

    def test_display_type_filter_param(self, client, db):
        """The renamed `display_type` query param filters the card endpoint."""
        _model(_title("Dmd", "dmd-title"), "dmd-m", display_type="dmd", year=2000)
        _model(_title("Lcd", "lcd-title"), "lcd-m", display_type="lcd", year=2000)
        data = client.get("/api/titles/?display_type=dmd").json()
        assert [i["slug"] for i in data["items"]] == ["dmd-title"]

    def test_query_count_ignores_other_facets(self, client, db):
        """`query_count` is the count for `q` **alone**, ignoring active facets —
        so the "create?" prompt can tell "this name is free" from "a facet is
        hiding an existing title". Filtering to Williams hides the Stern title
        (card count 0), but `query_count` still finds it by name."""
        _model(_title("Godzilla", "godzilla"), "g-m", manufacturer="stern")
        body = client.get("/api/pages/titles?q=Godzilla&manufacturer=williams").json()
        assert body["query_count"] == 1
        # The card endpoint under the same filters returns nothing (facet hides it).
        cards = client.get("/api/titles/?q=Godzilla&manufacturer=williams").json()
        assert cards["count"] == 0

    def test_query_count_null_without_q(self, client, db):
        """No search term ⇒ no query-only count (the prompt never shows without
        a `q`), so the field is null rather than a misleading total."""
        _model(_title("Solo", "solo"), "solo-m", manufacturer="williams")
        body = client.get("/api/pages/titles").json()
        assert body["query_count"] is None

    def test_query_count_matches_card_count_for_q_alone(self, client, db):
        """With `q` the only active filter, `query_count` equals the card
        endpoint's `count` for that `q` — the badge==result-count invariant,
        guarding against the q-only count drifting from search (distinct dedup,
        diacritic fold, first-model manufacturer)."""
        _model(_title("Godzilla", "godzilla"), "gz-m", manufacturer="stern")
        _model(
            _title("Godzilla Premium", "godzilla-prem"), "gzp-m", manufacturer="stern"
        )
        _model(_title("Other", "other"), "o-m", manufacturer="williams")
        page = client.get("/api/pages/titles?q=godzilla").json()
        cards = client.get("/api/titles/?q=godzilla").json()
        assert page["query_count"] == cards["count"] == 2


# ---------------------------------------------------------------------------
# Query-count regression guards — cost independent of row count
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_clear_cache")
class TestQueryCounts:
    """Both endpoints must run a fixed number of queries regardless of how many
    titles exist — catching a per-title N+1 in the facet fan-out or a
    ``list(qs)``-over-the-whole-catalog regression in the card path."""

    def _make_titles(self, start: int, n: int) -> None:
        for i in range(start, start + n):
            _model(
                _title(f"T{i}", f"t{i}"),
                f"t{i}-m",
                manufacturer="williams",
                system="wpc-95",
                player_count=4,
                year=2000 + i,
                themes=("horror",),
                persons=("pat-lawlor",),
            )

    def test_list_titles_query_count_constant(self, client, db):
        self._make_titles(0, 5)
        with CaptureQueriesContext(connection) as a:
            client.get("/api/titles/")
        self._make_titles(5, 5)
        with CaptureQueriesContext(connection) as b:
            client.get("/api/titles/")
        assert len(a) == len(b)

    def test_page_facets_query_count_constant(self, client, db):
        self._make_titles(0, 5)
        # A filtered request bypasses the no-filter cache so the fan-out runs
        # live; the `q` also exercises `_query_only_count` (a single count,
        # independent of row count) so a per-title regression there is caught too.
        url = "/api/pages/titles?manufacturer=williams&q=T"
        with CaptureQueriesContext(connection) as a:
            client.get(url)
        self._make_titles(5, 5)
        with CaptureQueriesContext(connection) as b:
            client.get(url)
        assert len(a) == len(b)
        # And the fan-out is bounded (the ~13 N-1 tallies + expansions), not O(rows).
        assert len(a) < 30
