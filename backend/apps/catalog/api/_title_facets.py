"""Server-side faceted filtering for the titles listing page.

This is the single source of truth for *how a set of title filters narrows the
catalog* — used by both the resource list endpoint (``GET /api/titles/``,
infinite-scroll pages 2…N) and the page endpoint (``GET /api/pages/titles``,
SSR first paint + facet option lists).

It ports the client-side ``facet-engine.ts`` to the ORM, with two **deliberate
divergences** (both documented at their sites): the ``player_count`` "6+" facet
count tallies distinct titles rather than the client's double-counting badge, and
``q`` title-name search is diacritic-insensitive on Postgres (``LOWER(UNACCENT)``)
but plain ``icontains`` on SQLite (dev/CI) — a documented dev/prod difference;
punctuation is not folded either way. Otherwise:

- :func:`filtered_titles` applies one narrower per dimension in a loop, skipping
  an optionally-``exclude``-d dimension. ``exclude=None`` serves the page query;
  ``exclude=<facet>`` serves that facet's N-1 count (count every value of a facet
  over titles passing all *other* filters — counts and value-pruning are the same
  ``GROUP BY``: a value with count 0 simply isn't returned).
- :func:`facet_counts` assembles the per-dimension ``{public_id, name, count}`` option
  lists the sidebar renders (``public_id`` is the option entity's URL identity — a slug
  for titles' facets; the name is generic because the shared leaves serve location too).

Four predicates are not the plain ``.filter()`` they look like — see the inline
notes on ``q`` (first-model manufacturer, the parity trap), ``year`` (range
overlap), ``rating`` (max-across-models) and ``player_count`` (the ``>=6``
bucket). "Manufacturer of a title" means its *first/original model's*
manufacturer, uniformly across the card, the manufacturer facet and ``q``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import connection
from django.db.models import (
    Count,
    F,
    Max,
    Model,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Lower

from apps.core.models import EntityStatus, active_status_q

from ..models import (
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
)
from ._facet_helpers import (
    Bounds,
    FacetOption,
    _fold,
    _Unaccent,
    ancestor_map,
    bounds,
    count_distinct,
    hierarchy_rollup,
    with_selected,
)

# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TitleFilters:
    """Every filter dimension for the titles listing, in real field-name
    vocabulary (one vocabulary end to end: URL params → this dataclass →
    queryset). Empty/``None`` means "dimension inactive"."""

    q: str = ""
    manufacturer: str | None = None
    person: str | None = None
    tech_gen: str | None = None
    display_type: str | None = None
    system: str | None = None
    franchise: str | None = None
    series: str | None = None
    player_count: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    rating_min: float | None = None
    themes: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    reward_types: tuple[str, ...] = ()


# dataclass, not NamedTuple: a NamedTuple field named ``count`` would shadow
# tuple.count and mypy rejects it.
@dataclass(frozen=True)
class PlayerCountOption:
    """A player-count bucket (the ``6`` bucket means "6 or more")."""

    value: int
    count: int


@dataclass(frozen=True)
class FilterOptions:
    """The full set of option lists for the sidebar — value-pruned and counted.
    Range dimensions (year, rating) return bounds, not value lists."""

    manufacturer: list[FacetOption] = field(default_factory=list)
    person: list[FacetOption] = field(default_factory=list)
    tech_gen: list[FacetOption] = field(default_factory=list)
    display_type: list[FacetOption] = field(default_factory=list)
    system: list[FacetOption] = field(default_factory=list)
    reward_type: list[FacetOption] = field(default_factory=list)
    theme: list[FacetOption] = field(default_factory=list)
    feature: list[FacetOption] = field(default_factory=list)
    franchise: list[FacetOption] = field(default_factory=list)
    series: list[FacetOption] = field(default_factory=list)
    player_count: list[PlayerCountOption] = field(default_factory=list)
    year: Bounds[int] = Bounds(None, None)
    rating: Bounds[float] = Bounds(None, None)


# ---------------------------------------------------------------------------
# Base queryset
# ---------------------------------------------------------------------------

# "Active non-variant model" — the relationship the card and every model-level
# facet derive from. Passing this Q first in a per-dimension ``.filter(_MODEL,
# <cond>)`` pins both onto the *same* join: "exists a model that is active,
# non-variant AND satisfies <cond>".
_MODEL = Q(machine_models__variant_of__isnull=True) & active_status_q("machine_models")

# The same active-non-variant rule expressed at the **MachineModel root** (no
# ``machine_models__`` prefix) — the *guard* the shared count/bounds leaves apply.
# Equivalent to ``.filter(variant_of__isnull=True).active()``; spelled as one Q so it
# can be passed as an argument. ``active()`` is null-inclusive for legacy ingest.
_MODEL_COUNT_GUARD = Q(variant_of__isnull=True) & (
    Q(status=EntityStatus.ACTIVE) | Q(status__isnull=True)
)

# Earliest non-variant active model by (year, name) — the title's "first model",
# whose manufacturer is the title's canonical manufacturer (mirrors /all/).
_FIRST_MODEL = (
    MachineModel.objects.filter(title=OuterRef("pk"), variant_of__isnull=True)
    .active()
    .order_by("year", "name")
)

# Correlated "first model's manufacturer" lookups. Used ONLY on demand — by the
# `q` and `manufacturer` *filters* (see apply_dimension). They are NOT in
# base_titles(): Postgres profiling showed these correlated subqueries run ~2× per
# title and cost ~280 ms over the full 6k-title set, taxing every no-filter request
# even when nothing filters by manufacturer. The manufacturer *facet count* derives
# the same value via a single ordered query + Python rollup (see _count_manufacturer)
# instead of grouping by these subqueries.
_MFR_SLUG_SQ = Subquery(_FIRST_MODEL.values("corporate_entity__manufacturer__slug")[:1])
_MFR_NAME_SQ = Subquery(_FIRST_MODEL.values("corporate_entity__manufacturer__name")[:1])

# Player-count buckets shown in the UI (``6`` == "6 or more"), matching the
# client's buildPlayerCountOptions. Values like 3 or 5 are foldable but unshown.
PLAYER_BUCKETS: tuple[int, ...] = (1, 2, 4, 6)


def base_titles() -> QuerySet[Title]:
    """Active titles — the unfiltered base for the page query and every facet
    count. Carries **no annotation**: the first-model-manufacturer subqueries are
    applied on demand only by the `q`/`manufacturer` narrowers (they're correlated
    and expensive on Postgres), and ``latest_year`` is added only in
    :func:`ordered_titles`. So the facet ``pk__in`` subqueries built off this base
    are bare ``SELECT id`` — no correlated subquery, no stray ``GROUP BY``."""
    return Title.objects.active()


# ---------------------------------------------------------------------------
# Per-dimension narrowers
# ---------------------------------------------------------------------------

# Order is irrelevant to the result (AND is commutative) but fixed so the N-1
# ``exclude`` keys are a closed, documented set.
DIMENSIONS: tuple[str, ...] = (
    "q",
    "manufacturer",
    "person",
    "tech_gen",
    "display_type",
    "system",
    "franchise",
    "series",
    "player_count",
    "year",
    "rating",
    "themes",
    "features",
    "reward_types",
)


def apply_dimension(
    qs: QuerySet[Title], key: str, f: TitleFilters, expansion: TaxonomyExpansion
) -> QuerySet[Title]:
    """Apply the single narrower named *key* (no-op if its filter is inactive).

    Each model-level dimension is its **own** ``.filter()`` call so Django emits
    a fresh join per dimension → title-level *AND across dimensions / OR across a
    title's models* (the client semantics: "any model has system Y" AND "any
    model has theme Z"). Collapsing into one ``.filter(Q & Q)`` would wrongly
    demand a *single* model satisfy every dimension at once.

    *expansion* carries the theme/feature descendant slug-sets, pre-built once per
    request (see :func:`_expand_taxonomy`) so this isn't re-scanning the taxonomy
    tables on each of the ~14 ``filtered_titles`` calls a facet fan-out makes.
    """
    match key:
        case "q" if f.q.strip():
            # Trim once at the boundary so search and `query_count` agree on a
            # whitespace-only `q` (both treat it as no filter) and so surrounding
            # spaces don't leak (`q=" williams "` must match "Williams").
            q = f.q.strip()
            # Matches name / abbreviation / FIRST-model manufacturer (the parity
            # trap): _q_mfr_name is the single first-model value, NOT a join across
            # all models — so q=Williams won't match a title whose *second* model is
            # a Williams reissue while its card shows Bally. Annotated on demand here
            # (not in base_titles) so the correlated subquery only runs when q is
            # active. django-stubs can't see the annotate()-created field.
            qs = qs.annotate(_q_mfr_name=_MFR_NAME_SQ)
            if connection.vendor == "postgresql":
                # Diacritic-insensitive on the title NAME: LOWER(UNACCENT(name))
                # vs the folded term, so q="pokemon" matches "Pokémon". Postgres
                # only — on SQLite (dev/CI) name falls back to plain icontains
                # below (no diacritic folding; a documented dev/prod difference).
                # Abbreviation + manufacturer stay plain icontains (ASCII-dominant).
                qs = qs.annotate(_q_name_fold=Lower(_Unaccent(F("name"))))
                name_match = Q(_q_name_fold__contains=_fold(q))
            else:
                name_match = Q(name__icontains=q)
            return qs.filter(
                name_match
                | Q(abbreviations__value__icontains=q)
                | Q(_q_mfr_name__icontains=q)
            )
        case "manufacturer" if f.manufacturer:
            # First-model manufacturer, annotated on demand (see q above).
            return qs.annotate(_mfr_slug=_MFR_SLUG_SQ).filter(_mfr_slug=f.manufacturer)
        case "person" if f.person:
            return qs.filter(_MODEL, machine_models__credits__person__slug=f.person)
        case "tech_gen" if f.tech_gen:
            return qs.filter(
                _MODEL, machine_models__technology_generation__slug=f.tech_gen
            )
        case "display_type" if f.display_type:
            return qs.filter(_MODEL, machine_models__display_type__slug=f.display_type)
        case "system" if f.system:
            return qs.filter(_MODEL, machine_models__system__slug=f.system)
        case "franchise" if f.franchise:
            return qs.filter(franchise__slug=f.franchise)
        case "series" if f.series:
            return qs.filter(series__slug=f.series)
        case "player_count" if f.player_count is not None:
            # Same bucket logic the facet count uses (via _bucket_q), so filter
            # and count can't drift.
            return qs.filter(
                _MODEL & _bucket_q(f.player_count, prefix="machine_models__")
            )
        case "year" if f.year_min is not None or f.year_max is not None:
            # Range OVERLAP via two join filters (NOT a Min/Max annotation +
            # HAVING): "exists a model <= year_max" AND "exists a model >=
            # year_min". A title with no model years fails the join == the
            # client's matchesYear returning false for null bounds.
            if f.year_max is not None:
                qs = qs.filter(_MODEL, machine_models__year__lte=f.year_max)
            if f.year_min is not None:
                qs = qs.filter(_MODEL, machine_models__year__gte=f.year_min)
            return qs
        case "rating" if f.rating_min is not None:
            # "max-across-models >= min" == "exists a model with rating >= min".
            return qs.filter(_MODEL, machine_models__ipdb_rating__gte=f.rating_min)
        case "themes" if f.themes:
            # AND-of-ORs: every selected slug must match (one .filter each), each
            # pre-expanded to its descendant slugs (expansion.themes) so filtering
            # by a parent theme also matches child-tagged titles. _MODEL on every
            # join so a variant/retired model can't satisfy the filter while
            # contributing nothing to the card or the facet counts.
            for descendants in expansion.themes:
                qs = qs.filter(_MODEL, machine_models__themes__slug__in=descendants)
            return qs
        case "features" if f.features:
            for descendants in expansion.features:
                qs = qs.filter(
                    _MODEL, machine_models__gameplay_features__slug__in=descendants
                )
            return qs
        case "reward_types" if f.reward_types:
            for slug in f.reward_types:
                qs = qs.filter(_MODEL, machine_models__reward_types__slug=slug)
            return qs
        case _:
            return qs


def filtered_titles(
    f: TitleFilters,
    *,
    exclude: str | None = None,
    expansion: TaxonomyExpansion | None = None,
) -> QuerySet[Title]:
    """All active titles passing every active filter except *exclude*.

    ``exclude=None`` → the page result set. ``exclude=<dimension>`` → the base
    for that dimension's N-1 facet counts. *expansion* (theme/feature descendant
    sets) is built lazily for standalone calls; callers that loop — like
    :func:`facet_counts` — build it **once** and pass it so the taxonomy tables
    aren't re-scanned per call.
    """
    if expansion is None:
        expansion = _expand_taxonomy(f)
    qs = base_titles()
    for key in DIMENSIONS:
        if key != exclude:
            qs = apply_dimension(qs, key, f, expansion)
    return qs.distinct()


def ordered_titles(f: TitleFilters) -> QuerySet[Title]:
    """:func:`filtered_titles` in canonical sort: newest first, then name, then
    pk. The ``pk`` tie-break gives offset pagination a total order
    (``(latest_year, name)`` is not unique)."""
    return (
        filtered_titles(f)
        .annotate(latest_year=Max("machine_models__year", filter=_MODEL))
        .order_by(F("latest_year").desc(nulls_last=True), "name", "pk")
    )


# ---------------------------------------------------------------------------
# Facet counts (the N-1 rule)
# ---------------------------------------------------------------------------


def _facet_base(
    f: TitleFilters, exclude: str, expansion: TaxonomyExpansion
) -> QuerySet[Title]:
    """Titles passing all filters except *exclude* — the N-1 base for that
    facet's counts. Returns the queryset (not materialized ids); used only as a
    ``...__in=`` subquery, so Django selects just the pk. The count helpers group
    over a *fresh* ``Title``/``MachineModel`` queryset filtered by this rather than
    over ``filtered_titles()`` directly, keeping the new ``GROUP BY`` clean.
    *expansion* is the once-per-request taxonomy expansion threaded from
    :func:`facet_counts`."""
    return filtered_titles(f, exclude=exclude, expansion=expansion)


def _count_model_facet(ids: QuerySet[Title], path: str) -> list[FacetOption]:
    """Count distinct titles per value of a model-level facet (system, theme,
    person, …), restricted to **active non-variant** models so variants and
    retired models don't leak values the card never shows.

    *path* is the lookup from ``MachineModel`` to the facet's ``slug``/``name``
    holder (e.g. ``"system"``, ``"themes"``, ``"credits__person"``).
    """
    return count_distinct(
        MachineModel,
        ids,
        reverse_key="title_id",
        relation=path,
        guard=_MODEL_COUNT_GUARD,
    )


def _count_title_fk(ids: QuerySet[Title], path: str) -> list[FacetOption]:
    """Count distinct titles per value of a title-level FK facet (franchise,
    series) — rooted at ``Title`` with no model guard."""
    return count_distinct(Title, ids, reverse_key="pk", relation=path, guard=Q())


def _count_manufacturer(ids: QuerySet[Title]) -> list[FacetOption]:
    """Count titles per first-model manufacturer.

    Derives each title's first model (earliest non-variant active by year, name)
    from **one** ordered query and rolls up in Python, rather than grouping by the
    correlated first-model subquery — which Postgres profiling showed runs ~2× per
    title and dominates the no-filter fan-out (~280 ms → ~11 ms). DB-agnostic (no
    ``DISTINCT ON``); the data is small (~7k models). One manufacturer per title,
    so the tally is exact title counts."""
    rows = (
        MachineModel.objects.filter(title_id__in=ids, variant_of__isnull=True)
        .active()
        .order_by("title_id", "year", "name")
        .values_list(
            "title_id",
            "corporate_entity__manufacturer__slug",
            "corporate_entity__manufacturer__name",
        )
    )
    # Single pass: the first row for each title_id (the order_by makes it the
    # first model) is the title's manufacturer; tally one title per manufacturer.
    seen: set[int] = set()
    tally: dict[str, tuple[str, int]] = {}
    for title_id, slug, name in rows.iterator():
        if title_id in seen:
            continue
        seen.add(title_id)
        if slug is not None and name is not None:
            prev = tally.get(slug)
            tally[slug] = (name, (prev[1] if prev else 0) + 1)

    options = [FacetOption(slug, name, count) for slug, (name, count) in tally.items()]
    options.sort(key=lambda o: o.name)
    return options


def _bucket_q(bucket: int, *, prefix: str = "") -> Q:
    """The membership predicate for a player-count bucket (``6`` == "6 or
    more"), shared by the facet filter and the facet count so they can't drift.

    *prefix* points the lookup at the right table: ``""`` when querying
    ``MachineModel`` directly (the count), ``"machine_models__"`` when querying
    ``Title`` (the filter)."""
    field = f"{prefix}player_count"
    return Q(**{f"{field}__gte": 6}) if bucket >= 6 else Q(**{field: bucket})


def _count_player(ids: QuerySet[Title]) -> list[PlayerCountOption]:
    """Count distinct titles per player-count bucket in a single query via
    conditional aggregation (not one COUNT per bucket). The ``6`` bucket counts
    titles with any model of player_count >= 6; the others are exact matches —
    mirroring matchesPlayerCount."""
    row = (
        MachineModel.objects.filter(title_id__in=ids, variant_of__isnull=True)
        .active()
        .aggregate(
            **{
                f"b{bucket}": Count("title_id", filter=_bucket_q(bucket), distinct=True)
                for bucket in PLAYER_BUCKETS
            }
        )
    )
    return [PlayerCountOption(bucket, row[f"b{bucket}"]) for bucket in PLAYER_BUCKETS]


def _count_hierarchical(
    ids: QuerySet[Title], model_cls: type[Theme] | type[GameplayFeature], path: str
) -> list[FacetOption]:
    """Count distinct titles per taxonomy value, **rolled up to ancestors** so a
    parent's count includes child-tagged titles (mirrors the client expanding
    each title's tags to ancestors before counting).

    The hierarchy is tiny, so we pull ``(title_id, leaf_slug)`` pairs for the
    filtered set, expand each title's slugs to ancestors in Python, then count
    distinct titles per slug (the shared :func:`ancestor_map`/:func:`hierarchy_rollup`
    leaves; the pairs query is title-specific and stays here).
    """
    ancestors = ancestor_map(model_cls, "slug", "parents__slug")
    names = dict(model_cls.objects.values_list("slug", "name"))
    pairs = (
        MachineModel.objects.filter(title_id__in=ids, variant_of__isnull=True)
        .active()
        .exclude(**{f"{path}__slug": None})
        .values_list("title_id", f"{path}__slug")
    )
    return hierarchy_rollup(pairs.iterator(), ancestors, names)


def _bounds[N: (int, float)](
    ids: QuerySet[Title], lookup: str, cast: Callable[[float], N]
) -> Bounds[N]:
    """Min/max of a model-level numeric field over active non-variant models of
    the filtered set, coerced via *cast* (``int`` for year, ``float`` for
    rating)."""
    return bounds(
        MachineModel,
        ids,
        reverse_key="title_id",
        lookup=lookup,
        guard=_MODEL_COUNT_GUARD,
        cast=cast,
    )


def _with_selected(
    options: list[FacetOption],
    selected: tuple[str, ...],
    model_cls: type[Model],
) -> list[FacetOption]:
    """Re-include count-0 active selections, keyed by ``slug`` (the shared
    :func:`with_selected` leaf — titles' facet values are all slugs). Thin binder so
    :func:`facet_counts` reads unchanged."""
    return with_selected(options, selected, model_cls)


def _selected(value: str | None) -> tuple[str, ...]:
    """A single-select filter value as the tuple :func:`_with_selected` wants."""
    return (value,) if value else ()


def facet_counts(f: TitleFilters) -> FilterOptions:
    """Assemble every sidebar option list, each counted by the N-1 rule (its own
    dimension excluded). A value with count 0 isn't returned → that *is* the
    value-pruning.

    NOTE on naming: the ``exclude`` keys + ORM paths use Django's field names —
    plural for M2Ms (``themes``, ``features``, ``reward_types``) — while the
    ``FilterOptions`` output fields use the frontend/URL facet vocab, which is
    singular (``theme``, ``feature``, ``reward_type``). The plural→singular hops
    below are that mapping, not typos.
    """
    # Built once and threaded through every _facet_base call so the theme/feature
    # descendant expansion scans the taxonomy tables once, not ~14× per request.
    expansion = _expand_taxonomy(f)
    return FilterOptions(
        manufacturer=_with_selected(
            _count_manufacturer(_facet_base(f, "manufacturer", expansion)),
            _selected(f.manufacturer),
            Manufacturer,
        ),
        person=_with_selected(
            _count_model_facet(_facet_base(f, "person", expansion), "credits__person"),
            _selected(f.person),
            Person,
        ),
        tech_gen=_with_selected(
            _count_model_facet(
                _facet_base(f, "tech_gen", expansion), "technology_generation"
            ),
            _selected(f.tech_gen),
            TechnologyGeneration,
        ),
        display_type=_with_selected(
            _count_model_facet(
                _facet_base(f, "display_type", expansion), "display_type"
            ),
            _selected(f.display_type),
            DisplayType,
        ),
        system=_with_selected(
            _count_model_facet(_facet_base(f, "system", expansion), "system"),
            _selected(f.system),
            System,
        ),
        reward_type=_with_selected(
            _count_model_facet(
                _facet_base(f, "reward_types", expansion), "reward_types"
            ),
            f.reward_types,
            RewardType,
        ),
        theme=_with_selected(
            _count_hierarchical(_facet_base(f, "themes", expansion), Theme, "themes"),
            f.themes,
            Theme,
        ),
        feature=_with_selected(
            _count_hierarchical(
                _facet_base(f, "features", expansion),
                GameplayFeature,
                "gameplay_features",
            ),
            f.features,
            GameplayFeature,
        ),
        franchise=_with_selected(
            _count_title_fk(_facet_base(f, "franchise", expansion), "franchise"),
            _selected(f.franchise),
            Franchise,
        ),
        series=_with_selected(
            _count_title_fk(_facet_base(f, "series", expansion), "series"),
            _selected(f.series),
            Series,
        ),
        player_count=_count_player(_facet_base(f, "player_count", expansion)),
        year=_bounds(_facet_base(f, "year", expansion), "year", int),
        rating=_bounds(_facet_base(f, "rating", expansion), "ipdb_rating", float),
    )


# ---------------------------------------------------------------------------
# Taxonomy hierarchy helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaxonomyExpansion:
    """The theme/feature filter operands, pre-expanded to descendants once per
    request. One ``frozenset`` per selected slug (AND-of-ORs: each selected theme
    matches itself **or any descendant**). Empty when no theme/feature filter is
    active — the common no-filter path does zero taxonomy scans."""

    themes: tuple[frozenset[str], ...] = ()
    features: tuple[frozenset[str], ...] = ()


def _children_map(
    model_cls: type[Theme] | type[GameplayFeature],
) -> dict[str, set[str]]:
    """parent slug → direct child slugs, from one ``(slug, parents__slug)`` scan."""
    children: dict[str, set[str]] = {}
    for child, parent in model_cls.objects.values_list("slug", "parents__slug"):
        if parent is not None:
            children.setdefault(parent, set()).add(child)
    return children


def _descendants(slug: str, children: dict[str, set[str]]) -> frozenset[str]:
    """*slug* plus every descendant slug (filtering by a parent matches
    child-tagged titles), walked over an in-memory *children* map — no DB hit."""
    result: set[str] = set()
    stack = [slug]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, ()))
    return frozenset(result)


def _expand_taxonomy(f: TitleFilters) -> TaxonomyExpansion:
    """Expand the active theme/feature filter slugs to their descendant sets,
    scanning each taxonomy table **at most once** (and not at all when the
    dimension is inactive)."""
    themes: tuple[frozenset[str], ...] = ()
    if f.themes:
        children = _children_map(Theme)
        themes = tuple(_descendants(slug, children) for slug in f.themes)
    features: tuple[frozenset[str], ...] = ()
    if f.features:
        children = _children_map(GameplayFeature)
        features = tuple(_descendants(slug, children) for slug in f.features)
    return TaxonomyExpansion(themes=themes, features=features)
