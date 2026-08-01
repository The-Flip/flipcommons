"""Tests for the manufacturers faceting module (``apps.catalog.api._manufacturer_facets``).

``q`` coverage:

- **Branches** — name + own aliases (unconditional), CE names/aliases and location
  names (+ ancestors) only via **active** CEs.
- **The guard-scoping parity trap** — a pure *name* match survives even when the
  manufacturer has no active CE; an inactive CE's name/alias/location does **not**
  match (the guard is per-term, never global).
- **Location ancestor match** — a Chicago CE matches ``q=Illinois``/``q=USA``; the dual
  of the location-count rollup.
- **Two diacritic-fold contracts** — the SQL branches (name) are backend-specific
  (fold on Postgres, plain ``icontains`` on SQLite); the **location** branch folds in
  Python on **both** backends. See the module docstring for the rationale.
"""

from __future__ import annotations

from typing import NamedTuple, cast

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.api._manufacturer_facets import (
    MfrFilters,
    facet_counts,
    filtered,
    ordered,
    query_count,
)
from apps.catalog.api._typing import HasModelCount
from apps.catalog.cache import invalidate_response_cache, manufacturers_facets_key
from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityAlias,
    CorporateEntityLocation,
    Credit,
    CreditRole,
    Location,
    MachineModel,
    Manufacturer,
    ManufacturerAlias,
    Person,
    TechnologyGeneration,
    Title,
)
from apps.core.models import EntityStatus

from .conftest import SAMPLE_IMAGES

# ---------------------------------------------------------------------------
# Row builders — real catalog rows, no resolver. ``q`` reads the stored ``name``
# field directly, so no name claims are needed.
# ---------------------------------------------------------------------------


def _mfr(
    slug: str,
    *,
    name: str | None = None,
    status: str = EntityStatus.ACTIVE,
    aliases: tuple[str, ...] = (),
) -> Manufacturer:
    mfr = Manufacturer.objects.create(
        slug=slug, name=name or slug.replace("-", " ").title(), status=status
    )
    for value in aliases:
        ManufacturerAlias.objects.create(manufacturer=mfr, value=value)
    return mfr


def _ce(
    mfr: Manufacturer,
    slug: str,
    *,
    name: str | None = None,
    status: str = EntityStatus.ACTIVE,
    aliases: tuple[str, ...] = (),
    location: Location | None = None,
) -> CorporateEntity:
    ce = CorporateEntity.objects.create(
        slug=slug,
        name=name or slug.replace("-", " ").title(),
        manufacturer=mfr,
        status=status,
    )
    for value in aliases:
        CorporateEntityAlias.objects.create(corporate_entity=ce, value=value)
    if location is not None:
        CorporateEntityLocation.objects.create(corporate_entity=ce, location=location)
    return ce


def _loc(path: str, name: str, *, parent: Location | None = None) -> Location:
    return Location.objects.create(
        location_path=path,
        slug=path.rsplit("/", 1)[-1],
        name=name,
        location_type="city",
        parent=parent,
    )


_MODEL_SEQ = iter(range(1, 1_000_000))


def _model(
    ce: CorporateEntity,
    *,
    year: int | None = None,
    technology_generation: TechnologyGeneration | None = None,
    person: Person | None = None,
    status: str = EntityStatus.ACTIVE,
    variant_of: MachineModel | None = None,
    extra_data: dict[str, object] | None = None,
) -> MachineModel:
    """A MachineModel under *ce*'s manufacturer, with an auto Title. Optionally tagged
    with a year, tech generation and a design credit (the model-level facet inputs)."""
    n = next(_MODEL_SEQ)
    title = Title.objects.create(slug=f"title-{n}", name=f"Title {n}")
    model = MachineModel.objects.create(
        slug=f"model-{n}",
        name=f"Model {n}",
        title=title,
        corporate_entity=ce,
        year=year,
        technology_generation=technology_generation,
        status=status,
        variant_of=variant_of,
        extra_data=extra_data if extra_data is not None else {},
    )
    if person is not None:
        role, _ = CreditRole.objects.get_or_create(
            slug="design", defaults={"name": "Design"}
        )
        Credit.objects.create(model=model, person=person, role=role)
    return model


def _person(slug: str, name: str | None = None) -> Person:
    return Person.objects.create(slug=slug, name=name or slug.replace("-", " ").title())


def _tech(slug: str, name: str | None = None) -> TechnologyGeneration:
    return TechnologyGeneration.objects.create(
        slug=slug, name=name or slug.replace("-", " ").title()
    )


@pytest.fixture
def usa_il_chicago(db) -> tuple[Location, Location, Location]:
    """The ``USA → Illinois → Chicago`` location chain used by the ancestor tests."""
    usa = _loc("usa", "USA")
    il = _loc("usa/il", "Illinois", parent=usa)
    chicago = _loc("usa/il/chicago", "Chicago", parent=il)
    return usa, il, chicago


def _slugs(f: MfrFilters) -> set[str]:
    """The slug set of manufacturers matching *f* (order-independent)."""
    return set(filtered(f).values_list("slug", flat=True))


def _ordered_counts(f: MfrFilters) -> list[tuple[str, int]]:
    """``ordered(f)`` as ``(slug, model_count)`` pairs, in sort order. Reads
    ``model_count`` off each object via the ``HasModelCount`` cast (the annotation
    isn't a real field, so django-stubs can't see it on ``values_list``) — the same
    pattern the cards endpoint uses."""
    return [(m.slug, cast(HasModelCount, m).model_count) for m in ordered(f)]


# ---------------------------------------------------------------------------
# Name + alias + active-CE branches
# ---------------------------------------------------------------------------


class TestQBranches:
    def test_matches_name(self, db):
        _mfr("williams", name="Williams")
        _mfr("stern", name="Stern")
        assert _slugs(MfrFilters(q="william")) == {"williams"}

    def test_no_match(self, db):
        _mfr("williams", name="Williams")
        assert _slugs(MfrFilters(q="nope")) == set()

    def test_matches_own_alias_unconditionally(self, db):
        """The manufacturer's own aliases contribute with no active-CE requirement —
        here the manufacturer has no CE at all."""
        _mfr("wms", name="WMS Industries", aliases=("Williams",))
        assert _slugs(MfrFilters(q="williams")) == {"wms"}

    def test_matches_active_ce_name(self, db):
        mfr = _mfr("williams", name="Williams")
        _ce(mfr, "wec", name="Williams Electronic Games")
        # The CE-name term reaches it via a different string than the manufacturer name.
        assert _slugs(MfrFilters(q="electronic")) == {"williams"}

    def test_matches_active_ce_alias(self, db):
        mfr = _mfr("williams", name="Williams")
        _ce(mfr, "wec", name="Williams Electronics", aliases=("Williams Elektronik",))
        assert _slugs(MfrFilters(q="elektronik")) == {"williams"}


# ---------------------------------------------------------------------------
# The guard-scoping parity trap — the guard is per-term, never global
# ---------------------------------------------------------------------------


class TestQGuardScoping:
    def test_name_match_survives_without_active_ce(self, db):
        """A pure *name* match must survive even when the manufacturer has **no
        active CE** — the manufacturers analogue of titles' first-model ``q`` parity
        trap. A global ``AND active-CE`` guard would silently drop it."""
        mfr = _mfr("zzz-mfr", name="Zzz Mfr")
        _ce(mfr, "dead-ce", name="Defunct", status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(q="zzz")) == {"zzz-mfr"}

    def test_inactive_ce_name_does_not_match(self, db):
        """An inactive CE's **name** must not match — its only signal is behind the
        active-CE guard (leak-free Exists rooting)."""
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "zzz-ce", name="Zzz Corporation", status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(q="zzz")) == set()

    def test_inactive_ce_alias_does_not_match(self, db):
        mfr = _mfr("acme", name="Acme")
        _ce(
            mfr,
            "zzz-ce",
            name="Other",
            status=EntityStatus.DELETED,
            aliases=("Zzz Elektronik",),
        )
        assert _slugs(MfrFilters(q="elektronik")) == set()

    def test_inactive_ce_name_not_rescued_by_another_active_ce(self, db):
        """The keystone leak test: the manufacturer has a **separate active CE** that
        does *not* match ``q``. An outer multi-valued annotation + a sibling
        ``entities__status`` guard would let the inactive CE's name satisfy the match
        while the *other* active CE satisfied the guard (a separate-join leak). The
        ``Exists`` rooting keeps match + guard on one CE row, so this must not match.
        This is the scenario the single-CE tests above cannot exercise."""
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "live-ce", name="Acme Industries")  # active, does NOT match "zzz"
        _ce(mfr, "dead-ce", name="Zzz Corporation", status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(q="zzz")) == set()

    def test_inactive_ce_alias_not_rescued_by_another_active_ce(self, db):
        """CE-alias counterpart of the keystone leak test (its own ``Exists``)."""
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "live-ce", name="Acme Industries")  # active, no matching alias
        _ce(
            mfr,
            "dead-ce",
            name="Other",
            status=EntityStatus.DELETED,
            aliases=("Zzz Elektronik",),
        )
        assert _slugs(MfrFilters(q="elektronik")) == set()


# ---------------------------------------------------------------------------
# Location term — name or any ancestor, under the active-CE guard
# ---------------------------------------------------------------------------


class TestQLocation:
    def test_matches_leaf_location_name(self, db, usa_il_chicago):
        _, _, chicago = usa_il_chicago
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=chicago)
        assert _slugs(MfrFilters(q="chicago")) == {"acme"}

    def test_matches_ancestor_location_name(self, db, usa_il_chicago):
        """A CE in Chicago matches a search for any ancestor name (Illinois, USA) —
        the dual of the location-count rollup."""
        _, _, chicago = usa_il_chicago
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=chicago)
        assert _slugs(MfrFilters(q="illinois")) == {"acme"}
        assert _slugs(MfrFilters(q="usa")) == {"acme"}

    def test_inactive_ce_location_does_not_match(self, db, usa_il_chicago):
        """An inactive CE's location must not surface its manufacturer — the location
        term is guarded by active-CE, same as name/alias."""
        _, _, chicago = usa_il_chicago
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=chicago, status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(q="illinois")) == set()

    def test_inactive_ce_location_not_rescued_by_another_active_ce(
        self, db, usa_il_chicago
    ):
        """Location counterpart of the keystone leak test: a **separate active CE**
        located elsewhere must not rescue an inactive CE's in-range location."""
        _, _, chicago = usa_il_chicago
        canada = _loc("canada", "Canada")
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "live-ce", location=canada)  # active but not in Illinois
        _ce(mfr, "dead-ce", location=chicago, status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(q="illinois")) == set()

    def test_matches_ancestor_beyond_four_levels(self, db):
        """Location ancestor match is **depth-unlimited** (matching the location
        facet). A CE nested 6 deep still matches a top-country ``q``."""
        a = _loc("a", "Alpha")
        b = _loc("a/b", "Bravo", parent=a)
        c = _loc("a/b/c", "Charlie", parent=b)
        d = _loc("a/b/c/d", "Delta", parent=c)
        e = _loc("a/b/c/d/e", "Echo", parent=d)
        deep = _loc("a/b/c/d/e/f", "Foxtrot", parent=e)
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=deep)
        # "Alpha" is the 6th ancestor — depth-unlimited, so it still matches here.
        assert _slugs(MfrFilters(q="alpha")) == {"acme"}


# ---------------------------------------------------------------------------
# Diacritic fold — two contracts (see module docstring)
# ---------------------------------------------------------------------------


class TestQDiacritics:
    def test_name_fold_is_backend_specific(self, db):
        """The SQL-folded name branch folds diacritics on **Postgres** only; SQLite
        falls back to bare ``icontains``. Production is Postgres, so this is a
        documented dev/CI gap, not a user-facing regression."""
        _mfr("cafe-mfr", name="Café Royale")
        matched = _slugs(MfrFilters(q="cafe"))
        if connection.vendor == "postgresql":
            assert matched == {"cafe-mfr"}
        else:
            assert matched == set()

    def test_location_fold_is_both_backends(self, db):
        """The location branch folds in **Python**, so it matches on both backends —
        unlike the SQL name branch above. ``q=montreal`` matches a Montréal CE on
        Postgres **and** SQLite."""
        montreal = _loc("montreal", "Montréal")
        mfr = _mfr("ms-mfr", name="MS Mfr")
        _ce(mfr, "ms-ce", location=montreal)
        assert _slugs(MfrFilters(q="montreal")) == {"ms-mfr"}


# ---------------------------------------------------------------------------
# Dedup, empty, query_count
# ---------------------------------------------------------------------------


class TestQMisc:
    def test_distinct_dedup(self, db):
        """Multiple matching active CEs (or branches) yield the manufacturer once."""
        mfr = _mfr("williams", name="Williams")
        _ce(mfr, "wec1", name="Williams Electronics")
        _ce(mfr, "wec2", name="Williams Electronic Games")
        assert list(
            filtered(MfrFilters(q="williams")).values_list("slug", flat=True)
        ) == ["williams"]

    def test_empty_q_returns_all_active(self, db):
        _mfr("williams", name="Williams")
        _mfr("stern", name="Stern")
        _mfr("dead", name="Dead", status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(q="")) == {"williams", "stern"}

    def test_whitespace_q_is_no_filter(self, db):
        """A whitespace-only ``q`` is treated as no filter (returns all active) — and
        agrees with ``query_count`` (which returns ``None``); surrounding spaces are
        trimmed so they don't leak into the fold."""
        _mfr("williams", name="Williams")
        _mfr("stern", name="Stern")
        assert _slugs(MfrFilters(q="   ")) == {"williams", "stern"}

    def test_surrounding_spaces_trimmed(self, db):
        _mfr("williams", name="Williams")
        assert _slugs(MfrFilters(q="  william  ")) == {"williams"}

    def test_query_count_none_without_q(self, db):
        _mfr("williams", name="Williams")
        assert query_count(MfrFilters(q="")) is None

    def test_query_count_none_for_whitespace(self, db):
        _mfr("williams", name="Williams")
        assert query_count(MfrFilters(q="   ")) is None

    def test_query_count_counts_q_alone(self, db):
        _mfr("williams", name="Williams")
        _mfr("williams-amusement", name="Williams Amusement")
        _mfr("stern", name="Stern")
        assert query_count(MfrFilters(q="williams")) == 2


# ---------------------------------------------------------------------------
# Per-facet filtering (location descendant, year overlap, person, technology_generation)
# ---------------------------------------------------------------------------


class TestLocationFilter:
    def test_descendant_match_at_country_and_state(self, db, usa_il_chicago):
        """Selecting an ancestor path matches a CE located at any descendant — the
        dual of the count rollup. ``location=usa`` and ``location=usa/il`` both match a
        Chicago CE."""
        _, _, chicago = usa_il_chicago
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=chicago)
        assert _slugs(MfrFilters(location="usa")) == {"acme"}
        assert _slugs(MfrFilters(location="usa/il")) == {"acme"}
        assert _slugs(MfrFilters(location="usa/il/chicago")) == {"acme"}

    def test_inactive_ce_descendant_does_not_match(self, db, usa_il_chicago):
        _, _, chicago = usa_il_chicago
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=chicago, status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(location="usa")) == set()

    def test_guard_and_location_share_one_ce_row(self, db, usa_il_chicago):
        """A separate active CE elsewhere must not rescue an inactive in-range CE — the
        guard and the location condition live in one ``.filter()`` so a single active CE
        must satisfy both."""
        _, _, chicago = usa_il_chicago
        canada = _loc("canada", "Canada")
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "live-ce", location=canada)  # active, but not in Illinois
        _ce(mfr, "dead-ce", location=chicago, status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(location="usa/il")) == set()


class TestYearFilter:
    def test_span_overlap_gap_case(self, db):
        """Year is span-overlap, not "a model inside the range": a manufacturer with
        models in 1980 and 2000 matches ``1990–1995`` even though no single model falls
        inside it (the two bounds are satisfied by different models)."""
        mfr = _mfr("acme", name="Acme")
        ce = _ce(mfr, "acme-ce")
        _model(ce, year=1980)
        _model(ce, year=2000)
        assert _slugs(MfrFilters(year_min=1990, year_max=1995)) == {"acme"}

    def test_open_ended_min(self, db):
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), year=1985)
        assert _slugs(MfrFilters(year_min=1990)) == set()
        assert _slugs(MfrFilters(year_min=1980)) == {"acme"}

    def test_variant_model_does_not_satisfy(self, db):
        """A variant model's year can't satisfy the filter (the card never shows it)."""
        mfr = _mfr("acme", name="Acme")
        ce = _ce(mfr, "acme-ce")
        base = _model(ce, year=1980)
        _model(ce, year=2000, variant_of=base)
        # Only the 1980 base model is real → no overlap with 1995–1999.
        assert _slugs(MfrFilters(year_min=1995, year_max=1999)) == set()


class TestPersonAndTechGenFilters:
    def test_person_matches_any_model(self, db):
        pat = _person("pat-lawlor", "Pat Lawlor")
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), person=pat)
        other = _mfr("other", name="Other")
        _model(_ce(other, "other-ce"))
        assert _slugs(MfrFilters(person="pat-lawlor")) == {"acme"}

    def test_person_credit_only_on_deleted_model_excluded(self, db):
        """Persons use the active-non-variant model guard: a person whose only credit
        is on a deleted model must not match the filter."""
        pat = _person("pat-lawlor", "Pat Lawlor")
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), person=pat, status=EntityStatus.DELETED)
        assert _slugs(MfrFilters(person="pat-lawlor")) == set()

    def test_tech_gen_matches(self, db):
        ss = _tech("solid-state", "Solid State")
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), technology_generation=ss)
        _mfr("other", name="Other")
        assert _slugs(MfrFilters(technology_generation="solid-state")) == {"acme"}


class TestCombinedFilters:
    def test_and_across_dimensions(self, db):
        """Filters AND across dimensions but OR across a manufacturer's models."""
        ss = _tech("solid-state", "Solid State")
        em = _tech("electromechanical", "EM")
        a = _mfr("a", name="A")
        ce_a = _ce(a, "a-ce")
        _model(ce_a, year=1990, technology_generation=ss)
        b = _mfr("b", name="B")
        ce_b = _ce(b, "b-ce")
        _model(
            ce_b, year=1990, technology_generation=em
        )  # year matches, technology_generation doesn't
        f = MfrFilters(
            year_min=1985, year_max=1995, technology_generation="solid-state"
        )
        assert _slugs(f) == {"a"}

    def test_empty_result(self, db):
        _mfr("acme", name="Acme")
        assert _slugs(MfrFilters(technology_generation="nonexistent")) == set()


# ---------------------------------------------------------------------------
# Facet counts (N-1 rule)
# ---------------------------------------------------------------------------


def _counts(options) -> dict[str, int]:
    return {o.public_id: o.count for o in options}


class TestFacetCounts:
    def test_location_rolls_up_the_full_ancestor_chain(self, db, usa_il_chicago):
        """A Chicago count rolls into Illinois rolls into USA — assert the chain
        explicitly, not just value presence."""
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=usa_il_chicago[2])
        counts = _counts(facet_counts(MfrFilters()).location)
        assert counts == {"usa/il/chicago": 1, "usa/il": 1, "usa": 1}

    def test_location_sibling_cities_do_not_double_count_parent(self, db):
        """A manufacturer with active CEs in two sibling cities counts ONCE at the
        shared parent (distinct-manufacturer-id union, never summed leaf counts)."""
        usa = _loc("usa", "USA")
        il = _loc("usa/il", "Illinois", parent=usa)
        chicago = _loc("usa/il/chicago", "Chicago", parent=il)
        peoria = _loc("usa/il/peoria", "Peoria", parent=il)
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "ce-chi", location=chicago)
        _ce(mfr, "ce-peo", location=peoria)
        counts = _counts(facet_counts(MfrFilters()).location)
        assert counts["usa/il"] == 1
        assert counts["usa"] == 1

    def test_location_count_excludes_inactive_ce(self, db, usa_il_chicago):
        mfr = _mfr("acme", name="Acme")
        _ce(mfr, "acme-ce", location=usa_il_chicago[2], status=EntityStatus.DELETED)
        assert facet_counts(MfrFilters()).location == []

    def test_nullable_tech_gen_drops_null_option(self, db):
        """A model with no technology_generation produces no null option (it would
        fail schema validation)."""
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), technology_generation=None)
        assert facet_counts(MfrFilters()).technology_generation == []

    def test_person_count_excludes_deleted_model_credit(self, db):
        """Counts use the active-non-variant model guard, so a person credited only on
        a deleted model doesn't surface."""
        pat = _person("pat-lawlor", "Pat Lawlor")
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), person=pat, status=EntityStatus.DELETED)
        assert facet_counts(MfrFilters()).person == []

    def test_year_bounds(self, db):
        mfr = _mfr("acme", name="Acme")
        ce = _ce(mfr, "acme-ce")
        _model(ce, year=1980)
        _model(ce, year=2005)
        assert facet_counts(MfrFilters()).year == (1980, 2005)

    def test_badge_equals_result_count(self, db):
        """A facet value's count (no other filter active) equals the number of
        manufacturers ``filtered`` returns for that value alone."""
        ss = _tech("solid-state", "Solid State")
        for slug in ("a", "b", "c"):
            _model(
                _ce(_mfr(slug, name=slug.upper()), f"{slug}-ce"),
                technology_generation=ss,
            )
        counts = _counts(facet_counts(MfrFilters()).technology_generation)
        assert counts["solid-state"] == len(
            _slugs(MfrFilters(technology_generation="solid-state"))
        )
        assert counts["solid-state"] == 3

    def test_location_badge_equals_result_count(self, db, usa_il_chicago):
        """The rolled-up location count (a distinct path) must still satisfy
        badge==result-count: the ancestor badge equals the descendant-filter result."""
        _, _, chicago = usa_il_chicago
        peoria = _loc("usa/il/peoria", "Peoria", parent=usa_il_chicago[1])
        _ce(_mfr("a", name="A"), "a-ce", location=chicago)
        _ce(_mfr("b", name="B"), "b-ce", location=peoria)
        counts = _counts(facet_counts(MfrFilters()).location)
        # Two manufacturers in distinct Illinois cities → "usa/il" badge is 2, matching
        # the descendant filter (and not double-counted at the country level).
        assert counts["usa/il"] == len(_slugs(MfrFilters(location="usa/il"))) == 2
        assert counts["usa"] == len(_slugs(MfrFilters(location="usa"))) == 2

    def test_selected_pruned_to_zero_stays_visible(self, db):
        """A selected value pruned to count 0 stays in its list at count 0 (so the
        chip can resolve its name and stay deselectable)."""
        ss = _tech("solid-state", "Solid State")
        # technology_generation exists in the catalog but no manufacturer matches the combined
        # filter (year excludes the only solid-state manufacturer).
        mfr = _mfr("acme", name="Acme")
        _model(_ce(mfr, "acme-ce"), year=1980, technology_generation=ss)
        f = MfrFilters(year_min=2000, technology_generation="solid-state")
        assert not _slugs(f)
        by_id = {o.public_id: o for o in facet_counts(f).technology_generation}
        assert by_id["solid-state"].count == 0
        assert by_id["solid-state"].name == "Solid State"


class _Bag(NamedTuple):
    location_paths: frozenset[str]
    person: frozenset[str]
    technology_generation: frozenset[str]
    years: frozenset[int]


def _naive_location_counts(
    bags: dict[str, _Bag], ancestors: dict[str, set[str]]
) -> dict[str, int]:
    out: dict[str, int] = {}
    for bag in bags.values():
        rolled: set[str] = set()
        for path in bag.location_paths:
            rolled |= ancestors.get(path, {path})
        for path in rolled:
            out[path] = out.get(path, 0) + 1
    return out


class TestFacetCountParity:
    def test_location_counts_match_naive_rollup(self, db):
        usa = _loc("usa", "USA")
        il = _loc("usa/il", "Illinois", parent=usa)
        chicago = _loc("usa/il/chicago", "Chicago", parent=il)
        peoria = _loc("usa/il/peoria", "Peoria", parent=il)
        canada = _loc("canada", "Canada")
        a = _mfr("a", name="A")
        _ce(a, "a1", location=chicago)
        _ce(a, "a2", location=peoria)
        b = _mfr("b", name="B")
        _ce(b, "b1", location=canada)
        c = _mfr("c", name="C")
        _ce(c, "c1", location=chicago)

        bags = {
            "a": _Bag(
                frozenset({"usa/il/chicago", "usa/il/peoria"}),
                frozenset(),
                frozenset(),
                frozenset(),
            ),
            "b": _Bag(frozenset({"canada"}), frozenset(), frozenset(), frozenset()),
            "c": _Bag(
                frozenset({"usa/il/chicago"}), frozenset(), frozenset(), frozenset()
            ),
        }
        anc = {
            "usa": {"usa"},
            "usa/il": {"usa/il", "usa"},
            "usa/il/chicago": {"usa/il/chicago", "usa/il", "usa"},
            "usa/il/peoria": {"usa/il/peoria", "usa/il", "usa"},
            "canada": {"canada"},
        }
        assert _counts(facet_counts(MfrFilters()).location) == _naive_location_counts(
            bags, anc
        )


# ---------------------------------------------------------------------------
# Ordering + model_count
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_most_prolific_first_then_name_then_pk(self, db):
        ss = _tech("solid-state", "Solid State")
        a = _mfr("aaa", name="Aaa")
        _model(_ce(a, "aaa-ce"), technology_generation=ss)
        _model(_ce(a, "aaa-ce2"), technology_generation=ss)
        c = _mfr("ccc", name="Ccc")
        _model(_ce(c, "ccc-ce"), technology_generation=ss)
        _model(_ce(c, "ccc-ce2"), technology_generation=ss)
        b = _mfr("bbb", name="Bbb")
        _model(_ce(b, "bbb-ce"))
        rows = _ordered_counts(MfrFilters())
        # 2-model manufacturers first (name tiebreak Aaa < Ccc), then the 1-model one.
        assert rows == [("aaa", 2), ("ccc", 2), ("bbb", 1)]

    def test_model_count_is_filter_independent(self, db):
        """The card's ``model_count`` is the manufacturer's TOTAL active-non-variant
        models, regardless of which facets are active (it must not shrink to the
        surviving models)."""
        mfr = _mfr("acme", name="Acme")
        ce = _ce(mfr, "acme-ce")
        _model(ce, year=1990)
        _model(ce, year=1995)
        _model(ce, year=2000)
        rows = dict(_ordered_counts(MfrFilters(year_min=1999)))
        assert rows == {"acme": 3}

    def test_zero_model_manufacturer_reads_zero_and_sorts_last(self, db):
        """A manufacturer with no active non-variant models reads 0 (the ``Coalesce``
        guard — not null) and sorts after manufacturers with models."""
        ss = _tech("solid-state", "Solid State")
        prolific = _mfr("prolific", name="Prolific")
        _model(_ce(prolific, "p-ce"), technology_generation=ss)
        _mfr("empty", name="Empty")  # no CEs, no models
        rows = _ordered_counts(MfrFilters())
        assert rows == [("prolific", 1), ("empty", 0)]

    def test_variant_only_manufacturer_reads_zero(self, db):
        mfr = _mfr("acme", name="Acme")
        ce = _ce(mfr, "acme-ce")
        base = _model(ce, year=1980)
        _model(ce, year=1981, variant_of=base)
        # 1 non-variant base model.
        assert dict(_ordered_counts(MfrFilters())) == {"acme": 1}


# ---------------------------------------------------------------------------
# Cards endpoint (GET /api/manufacturers/) + page endpoint
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_clear_cache")
class TestCardsEndpoint:
    @pytest.fixture
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_returns_items_and_count(self, client, db):
        ss = _tech("solid-state", "Solid State")
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"), technology_generation=ss)
        body = client.get("/api/manufacturers/").json()
        assert body["count"] == 1
        assert body["items"][0]["slug"] == "acme"
        assert body["items"][0]["model_count"] == 1
        assert set(body["items"][0]) == {
            "name",
            "slug",
            "model_count",
            "thumbnail_url",
        }

    def test_pagination_slices_at_sql(self, client, db):
        for i in range(55):
            _model(_ce(_mfr(f"m{i:02d}", name=f"M{i:02d}"), f"m{i:02d}-ce"))
        page1 = client.get("/api/manufacturers/?page=1").json()
        page2 = client.get("/api/manufacturers/?page=2").json()
        assert page1["count"] == 55
        assert len(page1["items"]) == 50
        assert len(page2["items"]) == 5

    def test_filter_param_narrows_cards(self, client, db):
        ss = _tech("solid-state", "Solid State")
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"), technology_generation=ss)
        _model(_ce(_mfr("other", name="Other"), "other-ce"))
        data = client.get(
            "/api/manufacturers/?technology_generation=solid-state"
        ).json()
        assert [i["slug"] for i in data["items"]] == ["acme"]

    def test_thumbnail_is_newest_model_with_extra_data(self, client, db):
        """The card thumbnail is the manufacturer's **newest active non-variant model
        that has extra_data** (year DESC, first-wins). The newer model's backglass
        medium URL wins over an older model's image."""
        ce = _ce(_mfr("acme", name="Acme"), "acme-ce")
        _model(
            ce,
            year=1990,
            extra_data={
                "opdb.images": [
                    {
                        "primary": True,
                        "type": "backglass",
                        "urls": {"medium": "https://img.opdb.org/old-md.jpg"},
                    }
                ]
            },
        )
        _model(ce, year=2020, extra_data={"opdb.images": SAMPLE_IMAGES})
        body = client.get("/api/manufacturers/").json()
        assert body["items"][0]["thumbnail_url"] == "https://img.opdb.org/md.jpg"

    def test_thumbnail_is_null_without_extra_data(self, client, db):
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"))
        body = client.get("/api/manufacturers/").json()
        assert body["items"][0]["thumbnail_url"] is None

    def test_query_count_constant_in_row_count(self, client, db):
        """The cards endpoint's query count must not grow with the number of
        manufacturers — guards the hand-rolled ``_page_thumbnails`` batch against an
        N+1 regression (a per-card thumbnail lookup would pass every other test)."""
        for i in range(3):
            _model(
                _ce(_mfr(f"a{i}", name=f"A{i}"), f"a{i}-ce"),
                year=2000,
                extra_data={"opdb.images": SAMPLE_IMAGES},
            )
        with CaptureQueriesContext(connection) as a:
            client.get("/api/manufacturers/")
        for i in range(3, 9):
            _model(
                _ce(_mfr(f"a{i}", name=f"A{i}"), f"a{i}-ce"),
                year=2000,
                extra_data={"opdb.images": SAMPLE_IMAGES},
            )
        with CaptureQueriesContext(connection) as b:
            client.get("/api/manufacturers/")
        assert len(a) == len(b)


@pytest.mark.usefixtures("_clear_cache")
class TestPageEndpoint:
    @pytest.fixture
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_shape_is_filter_options_and_query_count(self, client, db):
        _model(
            _ce(_mfr("acme", name="Acme"), "acme-ce"),
            technology_generation=_tech("solid-state", "Solid State"),
        )
        body = client.get("/api/pages/manufacturers").json()
        assert set(body) == {"filter_options", "query_count"}
        opts = body["filter_options"]
        assert set(opts) == {"location", "person", "technology_generation", "year"}
        assert set(opts["technology_generation"][0]) == {"public_id", "name", "count"}
        assert set(opts["year"]) == {"min", "max"}

    def test_badge_equals_result_count(self, client, db):
        ss = _tech("solid-state", "Solid State")
        for slug in ("a", "b"):
            _model(
                _ce(_mfr(slug, name=slug.upper()), f"{slug}-ce"),
                technology_generation=ss,
            )
        facets = client.get("/api/pages/manufacturers").json()["filter_options"]
        opt = next(
            o
            for o in facets["technology_generation"]
            if o["public_id"] == "solid-state"
        )
        result = client.get(
            "/api/manufacturers/?technology_generation=solid-state"
        ).json()["count"]
        assert opt["count"] == result == 2

    def test_no_filter_response_is_cached(self, client, db):
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"))
        with CaptureQueriesContext(connection) as miss:
            first = client.get("/api/pages/manufacturers")
        with CaptureQueriesContext(connection) as hit:
            second = client.get("/api/pages/manufacturers")
        assert first.json() == second.json()
        assert first["ETag"] == second["ETag"]
        assert len(hit) < len(miss)

    def test_filtered_response_is_not_cached(self, client, db):
        _model(
            _ce(_mfr("acme", name="Acme"), "acme-ce"),
            technology_generation=_tech("solid-state", "Solid State"),
        )
        client.get("/api/pages/manufacturers?technology_generation=solid-state")
        assert cache.get(manufacturers_facets_key()) is None

    def test_cache_invalidation_busts_both_audience_slots(self, client, db):
        """``invalidate_response_cache`` must clear both the ``default`` and ``kiosk`` slots so a
        catalog edit can't leave a stale facet payload behind in either."""
        _tech("solid-state", "Solid State")
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"))
        # Populate both audience slots.
        client.get("/api/pages/manufacturers")
        client.get("/api/pages/manufacturers", headers={"Cookie": "mode=kiosk"})
        base = manufacturers_facets_key().rsplit(":", 1)[0]
        assert cache.get(f"{base}:default") is not None
        assert cache.get(f"{base}:kiosk") is not None

        invalidate_response_cache()
        assert cache.get(f"{base}:default") is None
        assert cache.get(f"{base}:kiosk") is None

    def test_query_count_ignores_other_facets(self, client, db):
        ss = _tech("solid-state", "Solid State")
        # "Acme" has solid-state; "Beta" matches q but not the technology_generation filter.
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"), technology_generation=ss)
        _mfr("beta", name="Beta")
        body = client.get(
            "/api/pages/manufacturers?q=Beta&technology_generation=solid-state"
        ).json()
        assert body["query_count"] == 1
        cards = client.get(
            "/api/manufacturers/?q=Beta&technology_generation=solid-state"
        ).json()
        assert cards["count"] == 0

    def test_query_count_null_without_q(self, client, db):
        _model(_ce(_mfr("acme", name="Acme"), "acme-ce"))
        assert client.get("/api/pages/manufacturers").json()["query_count"] is None

    def test_facets_query_count_constant_in_row_count(self, client, db):
        """A filtered page request (bypasses the cache) runs the N-1 fan-out + the
        single ``query_count`` live; its query count must be independent of the number
        of manufacturers and bounded (not O(rows))."""
        _tech("solid-state", "Solid State")
        for i in range(3):
            _model(_ce(_mfr(f"a{i}", name=f"A{i}"), f"a{i}-ce"))
        url = "/api/pages/manufacturers?location=usa&q=A"
        with CaptureQueriesContext(connection) as a:
            client.get(url)
        for i in range(3, 9):
            _model(_ce(_mfr(f"a{i}", name=f"A{i}"), f"a{i}-ce"))
        with CaptureQueriesContext(connection) as b:
            client.get(url)
        assert len(a) == len(b)
        assert len(a) < 30
