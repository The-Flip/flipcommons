"""Server-side faceted filtering for the manufacturers listing page.

Manufacturers' parallel to ``_title_facets.py`` — its own explicit ``filtered`` /
``facet_counts`` assembly calling the shared leaves in ``_facet_helpers.py``,
free to diverge where manufacturers genuinely differ from titles.

Like titles, it applies one narrower per dimension in an N-1 loop (:func:`filtered`),
serves the page result via :func:`ordered`, and assembles the sidebar option lists in
:func:`facet_counts`. Where manufacturers genuinely differ from titles:

- **Filter side anchors at the model through the CE:** ``entities__models`` (a
  manufacturer's models hang off its corporate entities). The active-non-variant
  ``_MODEL`` guard rides every model-level narrower; counts root at the
  ``MachineModel`` model with the bare ``_MODEL_COUNT_GUARD``.
- **Location** is the dual pair titles' taxonomy facets are: the count rolls a
  Chicago count *up* into Illinois/USA (``hierarchy_rollup``); the filter selects a
  chosen ``location_path`` *down* into its descendants (path-prefix match). Both run
  under the active-CE guard. Location roots at ``CorporateEntityLocation`` (location
  hangs off the CE, not a model), so its count uses the active-CE guard, not
  ``_MODEL_COUNT_GUARD``.
- **Year is span-overlap**, not "a model inside the range": two separate
  ``.filter()`` calls (``__lte=year_max`` AND ``__gte=year_min``) so different models
  can satisfy the two bounds.
- **Person uses the active-non-variant model guard** — a deliberate divergence from
  ``/all/``, which builds persons from ``Credit`` with no model-active filter and so
  surfaces people whose only credit is on a retired model. Here those are excluded.
- **``model_count`` is a filter-independent ``Subquery``** (the card's total
  active-non-variant model count, and the "most prolific first" sort key) —
  ``Coalesce``-d to 0 so a manufacturer with no such models reads 0 and sorts last.

The ``q`` predicate (the subtle part):

- It matches the same **fields** ``/all/`` builds its blob from: the **manufacturer
  name + its own aliases unconditionally**, and **CE names, CE aliases and location
  names (+ ancestors) only via active CEs**. The active-CE guard is therefore
  **per-term, inside the CE-reached branches**, never a global ``AND`` — a global
  guard would drop a manufacturer with no active CE from a pure *name* match (the
  manufacturers analogue of titles' first-model ``q`` parity trap). **One deliberate
  divergence from ``/all/``: location ancestor depth.** ``/all/`` walks only the
  nearest **four** parents ([manufacturers.py] ``list_all_manufacturers``); the
  location term here is **depth-unlimited** (the shared ``ancestor_map``), matching the
  same improvement the location *facet* makes so search and facet counts agree. A CE
  nested 5+ deep therefore matches a top-country ``q`` here where ``/all/`` would miss
  it — the correct behavior (a country search should find all its manufacturers), and
  pinned by a test.
- **Each guarded CE branch is an ``Exists`` subquery rooted at the CE-side model**,
  not an outer ``.annotate(Lower(Unaccent(F("entities__name"))))`` + a separate
  ``entities__status`` guard. Rooting the match and the active guard in one
  subquery ``WHERE`` keeps them on the *same row* — the same separate-join trap the
  count leaves avoid. An outer multi-valued annotation + a sibling guard could let
  an **inactive** CE's name match while a **different** active CE satisfied the
  guard. The manufacturer-own terms (name, own aliases) are unguarded, so they stay
  as a plain outer annotation / own-alias ``Exists``.
- **Diacritic fold, two mechanisms, two backend behaviors**:
  the SQL-folded fields (name, own aliases, CE names/aliases) fold via
  ``LOWER(UNACCENT(...))`` on **Postgres** and fall back to bare ``icontains`` on
  **SQLite** (same dev/prod split as titles). The **location** term can't be a SQL
  fold — it matches a location's name *or any ancestor's*, and ancestor names aren't
  an annotatable field — so it resolves in **Python** via ``_fold`` on **both**
  backends. Net dev-only asymmetry on SQLite: ``q=montreal`` matches a Montréal
  *location* but not a diacritic manufacturer *name*. Invisible in production
  (Postgres → every branch folds). Punctuation is not folded either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import connection
from django.db.models import (
    Count,
    Exists,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce, Lower

from apps.core.models import EntityStatus, active_status_q
from apps.core.search import fold as _fold

from ..models import (
    CorporateEntity,
    CorporateEntityAlias,
    CorporateEntityLocation,
    Location,
    MachineModel,
    Manufacturer,
    ManufacturerAlias,
    Person,
    TechnologyGeneration,
)
from ._facet_helpers import (
    Bounds,
    FacetOption,
    _fold_exists,
    _Unaccent,
    ancestor_map,
    bounds,
    count_distinct,
    hierarchy_rollup,
    with_selected,
)

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MfrFilters:
    """Every manufacturers-listing filter dimension, in real field-name vocabulary
    (one vocabulary end to end: URL params → this dataclass → queryset). All facets
    are **single-value** (no titles-style repeated multi-value params). Empty/``None``
    means "dimension inactive"."""

    q: str = ""
    location: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    person: str | None = None
    tech_gen: str | None = None


@dataclass(frozen=True)
class FilterOptions:
    """The sidebar option lists — value-pruned and counted (year is a range, so it
    returns bounds, not a value list)."""

    location: list[FacetOption] = field(default_factory=list)
    person: list[FacetOption] = field(default_factory=list)
    tech_gen: list[FacetOption] = field(default_factory=list)
    year: Bounds[int] = Bounds(None, None)


# ---------------------------------------------------------------------------
# Base queryset
# ---------------------------------------------------------------------------


def base() -> QuerySet[Manufacturer]:
    """Active manufacturers — the unfiltered base for the page query and every facet
    count. ``.active()`` is the only audience rule ``/all/`` applies to the
    manufacturer set itself (audience otherwise only affects thumbnails via
    ``min_rank``, which lives on the card path, not here)."""
    return Manufacturer.objects.active()


# ---------------------------------------------------------------------------
# Model anchor + guards (the filter side reaches a model through the CE)
# ---------------------------------------------------------------------------

# "Active non-variant model of this manufacturer" expressed on the **filter-side**
# anchor (``entities__models`` prefix). Passing this Q first in a per-dimension
# ``.filter(_MODEL, <cond>)`` pins both onto the same join: "exists a model that is
# active, non-variant AND satisfies <cond>".
_MODEL = Q(entities__models__variant_of__isnull=True) & active_status_q(
    "entities__models"
)

# The same active-non-variant rule at the **MachineModel root** (no prefix) — the
# guard the shared count/bounds leaves apply. Equivalent to
# ``.filter(variant_of__isnull=True).active()``; spelled as one Q so it can be passed
# as an argument. ``active()`` is null-inclusive for legacy ingest. (Manufacturers
# copies titles' ``_MODEL_COUNT_GUARD`` rather than sharing it — it names
# ``variant_of``, a MachineModel-specific field, so it is not domain-free.)
_MODEL_COUNT_GUARD = Q(variant_of__isnull=True) & (
    Q(status=EntityStatus.ACTIVE) | Q(status__isnull=True)
)

# Distinct count of a manufacturer's active non-variant models, as a correlated
# ``Subquery`` — the card's displayed ``model_count`` AND the "most prolific first"
# sort key. A ``Subquery`` (not ``Count(..., distinct=True)``) is immune to BOTH the
# M2M fan-out (credits/location joins duplicating rows) AND filter-scoping (an
# annotation sharing the filtered queryset's join would count only the surviving
# models). ``Coalesce(..., 0)``: a scalar count subquery returns NULL for a
# manufacturer with no active non-variant models (empty group → no row), but the card
# field is ``int`` and such manufacturers must sort **last**, not at a NULL boundary.
_MODEL_COUNT_SQ = Coalesce(
    Subquery(
        MachineModel.objects.filter(
            corporate_entity__manufacturer=OuterRef("pk"), variant_of__isnull=True
        )
        .active()
        .order_by()
        .values("corporate_entity__manufacturer")
        .annotate(c=Count("pk"))
        .values("c")
    ),
    0,
)


# ---------------------------------------------------------------------------
# `q` full-blob search
# ---------------------------------------------------------------------------


def _location_match_paths(q: str, folded: str) -> set[str]:
    """The ``location_path`` set a CE must be located at for ``q`` to match its
    location name **or any ancestor's**.

    Resolved in Python (so the fold runs on both backends — see module docstring): a
    location matches when any name on its self-or-ancestor chain folds-matches *q*.
    Using the shared :func:`ancestor_map` (each path → its ancestor paths incl.
    itself), a path is in the result iff its ancestor set intersects the hit set (the
    locations whose **own** name folds-matches). This is the dual of the location
    facet's count rollup: the rollup rolls a Chicago count *up* into Illinois; here a
    ``q=Illinois`` hit selects Chicago (and every other descendant) *down*, because
    Illinois is on Chicago's ancestor chain."""
    hits = {
        path
        for path, name in Location.objects.values_list("location_path", "name")
        if folded in _fold(name)
    }
    if not hits:
        return set()
    ancestors = ancestor_map(Location, "location_path", "parent__location_path")
    return {path for path, anc in ancestors.items() if anc & hits}


def _apply_q(qs: QuerySet[Manufacturer], q: str) -> QuerySet[Manufacturer]:
    """Narrow *qs* to manufacturers matching the full ``q`` blob.

    ``name OR own_alias OR (ce_name AND ce_active) OR (ce_alias AND ce_active)
    OR ((location_name OR ancestor_name) AND ce_active)`` — the guard living inside
    each CE-reached branch, never global (the parity trap). Guarded branches are
    ``Exists`` subqueries rooted CE-side so match + guard share a row; the unguarded
    own terms are an outer annotation (name, single-valued same row) and an own-alias
    ``Exists``."""
    folded = _fold(q)

    # Guarded CE-reached branches — Exists rooted where the active guard and the
    # fold match share one row (leak-free; see module docstring). Own aliases are
    # unguarded (they contribute unconditionally, like the manufacturer name).
    annotations = {
        "_q_own_alias": _fold_exists(
            ManufacturerAlias.objects.filter(manufacturer=OuterRef("pk")),
            "value",
            q,
            folded,
        ),
        "_q_ce_name": _fold_exists(
            CorporateEntity.objects.active().filter(manufacturer=OuterRef("pk")),
            "name",
            q,
            folded,
        ),
        "_q_ce_alias": _fold_exists(
            CorporateEntityAlias.objects.filter(
                corporate_entity__manufacturer=OuterRef("pk")
            ).filter(active_status_q("corporate_entity")),
            "value",
            q,
            folded,
        ),
    }

    # Location term — Python-resolved path set, descendant-matched under the active-CE
    # guard (in the same subquery WHERE). `match_paths` is bounded by the Location
    # table (~thousands), so the `__in` stays a single bounded clause; a broad `q`
    # widens it but never makes it correlated/per-row. Revisit with a prefix-range
    # form only if profiling on real data flags the IN size.
    match_paths = _location_match_paths(q, folded)
    if match_paths:
        annotations["_q_location"] = Exists(
            CorporateEntityLocation.objects.filter(
                corporate_entity__manufacturer=OuterRef("pk"),
                location__location_path__in=match_paths,
            ).filter(active_status_q("corporate_entity"))
        )

    qs = qs.annotate(**annotations)

    # Manufacturer name — unguarded, single-valued on the outer row, so a direct
    # outer annotation (Postgres) / icontains (SQLite), not an Exists.
    if connection.vendor == "postgresql":
        qs = qs.annotate(_q_name=Lower(_Unaccent(F("name"))))
        name_match = Q(_q_name__contains=folded)
    else:
        name_match = Q(name__icontains=q)

    predicate = (
        name_match | Q(_q_own_alias=True) | Q(_q_ce_name=True) | Q(_q_ce_alias=True)
    )
    if match_paths:
        predicate |= Q(_q_location=True)
    return qs.filter(predicate)


# ---------------------------------------------------------------------------
# Per-dimension narrowers + the N-1 loop
# ---------------------------------------------------------------------------

# Order is irrelevant to the result (AND is commutative) but fixed so the N-1
# ``exclude`` keys are a closed, documented set.
DIMENSIONS: tuple[str, ...] = ("q", "location", "year", "person", "tech_gen")


def apply_dimension(
    qs: QuerySet[Manufacturer], key: str, f: MfrFilters
) -> QuerySet[Manufacturer]:
    """Apply the single narrower named *key* (no-op if its filter is inactive).

    Each model-level dimension is its **own** ``.filter()`` call so Django emits a
    fresh join per dimension → manufacturer-level *AND across dimensions / OR across a
    manufacturer's models* (the client semantics). Collapsing into one
    ``.filter(Q & Q)`` would wrongly demand a *single* model satisfy every dimension.
    """
    match key:
        case "q" if f.q.strip():
            # Trim once at the boundary so search and `query_count` agree on a
            # whitespace-only `q` (both treat it as no filter) and so surrounding
            # spaces don't leak into the fold (`q=" williams "` must match "Williams").
            return _apply_q(qs, f.q.strip())
        case "location" if f.location:
            # Descendant-match — the dual of the count rollup. Selecting `usa` must
            # return a CE at `usa/il/chicago`, so match the chosen path OR any path
            # under it (`location_path` = parent.path + "/" + slug, so the prefix is
            # exact). The active-CE guard (`entities__...`) and the location condition
            # go in ONE `.filter()` so a single active CE row must satisfy both —
            # separate `.filter()`s would let any active CE plus any located CE match.
            sel = f.location
            return qs.filter(
                active_status_q("entities"),
                Q(entities__locations__location__location_path=sel)
                | Q(entities__locations__location__location_path__startswith=f"{sel}/"),
            )
        case "year" if f.year_min is not None or f.year_max is not None:
            # Span OVERLAP via two join filters (NOT one `year__range`): "exists a
            # model <= year_max" AND "exists a model >= year_min", satisfiable by
            # DIFFERENT models. A manufacturer with models in 1980 and 2000 overlaps
            # 1990–1995 even though no single model falls inside it.
            if f.year_max is not None:
                qs = qs.filter(_MODEL, entities__models__year__lte=f.year_max)
            if f.year_min is not None:
                qs = qs.filter(_MODEL, entities__models__year__gte=f.year_min)
            return qs
        case "person" if f.person:
            return qs.filter(_MODEL, entities__models__credits__person__slug=f.person)
        case "tech_gen" if f.tech_gen:
            return qs.filter(
                _MODEL, entities__models__technology_generation__slug=f.tech_gen
            )
        case _:
            return qs


def filtered(f: MfrFilters, *, exclude: str | None = None) -> QuerySet[Manufacturer]:
    """All active manufacturers passing every active filter except *exclude*.

    ``exclude=None`` → the page result set; ``exclude=<dimension>`` → the N-1 base
    for that dimension's facet counts."""
    qs = base()
    for key in DIMENSIONS:
        if key != exclude:
            qs = apply_dimension(qs, key, f)
    return qs.distinct()


def ordered(f: MfrFilters) -> QuerySet[Manufacturer]:
    """:func:`filtered` in canonical sort: most prolific first, then name, then pk.
    The ``pk`` tie-break gives offset pagination a total order (``(model_count,
    name)`` is not unique). ``model_count`` is annotated here (kept out of
    :func:`base`) and is the **same** filter-independent ``Subquery`` the card
    displays, so prolificacy ranking and the shown number can't drift."""
    return (
        filtered(f)
        .annotate(model_count=_MODEL_COUNT_SQ)
        .order_by("-model_count", "name", "pk")
    )


def query_count(f: MfrFilters) -> int | None:
    """Count manufacturers matching ``q`` **alone**, ignoring every other facet —
    drives the "create this manufacturer?" prompt. ``None`` when there is no ``q``
    (the prompt never shows without one). Reuses :func:`filtered` over a ``q``-only
    ``MfrFilters`` so it shares the exact ``q`` predicate and can't drift from search.

    Trim before testing: a whitespace-only ``q`` is empty to the (trimmed) prompt, so
    skip it rather than run a near-whole-catalog match."""
    if not f.q.strip():
        return None
    return filtered(MfrFilters(q=f.q)).count()


# ---------------------------------------------------------------------------
# Facet counts (the N-1 rule)
# ---------------------------------------------------------------------------

# ``reverse_key`` for every model-rooted count below: how a MachineModel row returns
# to the manufacturer it should be counted against.
_REVERSE_KEY = "corporate_entity__manufacturer_id"


def _count_model_facet(ids: QuerySet[Manufacturer], relation: str) -> list[FacetOption]:
    """Count distinct manufacturers per value of a model-level facet (person,
    tech_gen), restricted to **active non-variant** models so variants/retired models
    don't leak values the card never shows. *relation* is the count-root-relative path
    from ``MachineModel`` to the value holder (``credits__person``,
    ``technology_generation``)."""
    return count_distinct(
        MachineModel,
        ids,
        reverse_key=_REVERSE_KEY,
        relation=relation,
        guard=_MODEL_COUNT_GUARD,
    )


def _count_location(ids: QuerySet[Manufacturer]) -> list[FacetOption]:
    """Count distinct manufacturers per location, **rolled up to ancestors** so a
    parent's count includes manufacturers located in any descendant (a Chicago CE
    rolls into Illinois rolls into USA).

    Location roots at ``CorporateEntityLocation`` (location hangs off the CE, not a
    model), under the **active-CE** guard — not ``_MODEL_COUNT_GUARD``. Counting leaves
    then summing would double-count a manufacturer with active CEs in two sibling
    locations, so :func:`hierarchy_rollup` unions a distinct manufacturer-id set per
    ancestor ``location_path`` and takes ``len(set)``. The ancestor walk is
    depth-unlimited (drops ``/all/``'s 4-parent cap)."""
    ancestors = ancestor_map(Location, "location_path", "parent__location_path")
    names = dict(Location.objects.values_list("location_path", "name"))
    # `location` is a non-null FK, so every CEL row carries a path — no null group to
    # drop (unlike the nullable model-FK facets `count_distinct` guards against).
    pairs = CorporateEntityLocation.objects.filter(
        active_status_q("corporate_entity"),
        corporate_entity__manufacturer_id__in=ids,
    ).values_list("corporate_entity__manufacturer_id", "location__location_path")
    return hierarchy_rollup(pairs.iterator(), ancestors, names)


def _selected(value: str | None) -> tuple[str, ...]:
    """A single-select filter value as the tuple :func:`with_selected` wants."""
    return (value,) if value else ()


def facet_counts(f: MfrFilters) -> FilterOptions:
    """Assemble every sidebar option list, each counted by the N-1 rule (its own
    dimension excluded). A value with count 0 isn't returned → that *is* the
    value-pruning. Each list re-includes an active-but-pruned selection at count 0
    via :func:`with_selected` (location keyed on ``location_path``, the rest on
    ``slug``)."""
    return FilterOptions(
        location=with_selected(
            _count_location(filtered(f, exclude="location")),
            _selected(f.location),
            Location,
            public_id_field="location_path",
        ),
        person=with_selected(
            _count_model_facet(filtered(f, exclude="person"), "credits__person"),
            _selected(f.person),
            Person,
        ),
        tech_gen=with_selected(
            _count_model_facet(
                filtered(f, exclude="tech_gen"), "technology_generation"
            ),
            _selected(f.tech_gen),
            TechnologyGeneration,
        ),
        year=bounds(
            MachineModel,
            filtered(f, exclude="year"),
            reverse_key=_REVERSE_KEY,
            lookup="year",
            guard=_MODEL_COUNT_GUARD,
            cast=int,
        ),
    )
