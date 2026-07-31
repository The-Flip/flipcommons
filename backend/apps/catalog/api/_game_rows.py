"""Card-grain listing rows — the Title ➡ Model ➡ Variant roll-up engine.

The row engine behind ``GET /api/games/``: one row per *card*,
where a card is a Title when every one of its live Models matches the
Model-only dimensions (rung 1), else one card per matching Model (rung 2),
with a Variant absorbed into a matching parent (rung 3).

Rows only — serialization and the wire contract live in ``games.py``, and the
facet fan-out at card grain in ``_game_facets.py``, both built on this
module's two sets and rungs. The filter vocabulary is the full listing set,
by semantics class:

- ``manufacturer`` / ``person`` / ``tech_gen`` / ``display_type`` / ``system``
  — single-valued Model-only
- ``player_count`` — bucketed Model-only (``6`` means "6 or more", via the
  shared ``_bucket_q``)
- ``themes`` / ``features`` — multi-select Model-only (AND of ORs,
  descendant-expanded)
- ``reward_types`` — multi-select Model-only (AND, no hierarchy)
- ``edge`` — multi-select Model-only (AND, no hierarchy): relationship keys
  with an optional ``:in`` direction suffix (``_edge_vocabulary.py``); an
  unknown key matches nothing
- ``year_min``/``year_max`` — range, Model-only
- ``franchise`` / ``series`` — Title-only, binding all of a Title's Models
- ``q`` — the record-local shared class (name + abbreviations), tested on the
  record being decided and propagating in neither direction
- ``display_subtype`` / ``tag`` / ``technology_subgeneration`` / ``cabinet`` /
  ``game_format`` / ``production_status`` / ``corporate_entity`` — single-valued
  Model-only, **hidden** (``surfaced=False``): honored from the query string
  with full roll-up semantics, but no sidebar control and no facet counts.
  ``technology_subgeneration`` matches the Model's own FK *or* its system's;
  the sparse three (``cabinet``/``game_format``/``production_status``) are raw
  — ``game_format=pinball`` means exactly the classified minority

The two-set split is the engine's load-bearing invariant: **unanimity is
measured over** :func:`model_only_models` **(Model-only dimensions alone),
never over** :func:`carding_models` **(that plus the shared class)**. Feeding
``carding`` into the unanimity count silently inverts the product doc's worked
examples (``q=Ice Fever`` would return the Ice Fever Model where the Title
card is specified) — a plausible-looking wrong answer, not an error.

Rows come from :func:`game_rows_merged` — two queries merged and ordered in
Python (the ``_count_manufacturer`` precedent: ~7k-row scan + rollup). Two
properties of that seam the rest of the engine depends on: ``count`` is the
built list's length, so it can never drift from what the page slices, and the
ordering runs on a diacritic- and case-folded name key in Python, so it does
not vary with the database's collation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import (
    Final,
    Literal,
    NamedTuple,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

from django.db import connection
from django.db.models import (
    CharField,
    Count,
    Exists,
    F,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Value,
)

from apps.core.models import active_status_q
from apps.core.search import fold as _fold

from ..models import (
    GameplayFeature,
    MachineModel,
    ModelAbbreviation,
    Theme,
    Title,
    TitleAbbreviation,
)
from ._edge_vocabulary import edge_q, parse_edge_value

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GameFilters:
    """Every filter dimension for the games listing (see the module docstring
    for the semantics classes). Empty/``None`` means "dimension inactive"."""

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
    themes: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    reward_types: tuple[str, ...] = ()
    edge: tuple[str, ...] = ()
    display_subtype: str | None = None
    tag: str | None = None
    technology_subgeneration: str | None = None
    cabinet: str | None = None
    game_format: str | None = None
    production_status: str | None = None
    corporate_entity: str | None = None


# The closed dimension-key vocabularies. Literal, not str: an ``exclude``
# typo would otherwise not raise — it silently skips the N-1 exclusion and
# every badge for that facet goes quietly wrong.
ModelDimension = Literal[
    "manufacturer",
    "person",
    "tech_gen",
    "display_type",
    "system",
    "player_count",
    "year",
    "themes",
    "features",
    "reward_types",
    "edge",
    "display_subtype",
    "tag",
    "technology_subgeneration",
    "cabinet",
    "game_format",
    "production_status",
    "corporate_entity",
]
TitleDimension = Literal["franchise", "series"]

# The Model-only dimension keys, for N-1 facet exclusion — derived from the
# Literal so the runtime tuple and the type can't diverge. ``q`` is the
# record-local shared class and ``franchise``/``series`` are Title-only; none
# of the three is a Model-only dimension.
MODEL_DIMENSIONS: tuple[ModelDimension, ...] = get_args(ModelDimension)

# Filter-field types, resolved once. ``get_type_hints`` rather than raw
# ``__annotations__`` because this module uses ``from __future__ import
# annotations``, so the annotations are strings until resolved.
_FILTER_TYPES: Final[Mapping[str, object]] = get_type_hints(GameFilters)

# Dimensions whose selections **accumulate** (ANDed together) instead of
# replacing one another — derived from ``GameFilters``' own arity, since a
# tuple-typed field is precisely one that holds several values at once. Derived,
# not declared, so a new multi-valued dimension classifies itself.
#
# Deliberately NOT derived from ``MachineModel._meta`` many-to-many-ness: that
# is a different fact and would misclassify. ``person`` filters through the
# multivalued ``credits__person`` path yet takes a single value, so its relation
# is many-valued while its *filter* is not.
MULTI_DIMENSIONS: Final[frozenset[ModelDimension]] = frozenset(
    key for key in MODEL_DIMENSIONS if get_origin(_FILTER_TYPES.get(key)) is tuple
)

# ``year`` is the one dimension key naming no field of its own (it spans
# ``year_min``/``year_max``). Pin that, so a renamed or retyped field can't
# quietly read as single-valued and re-open the badge bug ``facet_exclude``
# below exists to prevent.
assert {key for key in MODEL_DIMENSIONS if key not in _FILTER_TYPES} == {"year"}


def facet_exclude(key: ModelDimension) -> ModelDimension | None:
    """The N-1 exclusion for *key*'s own facet base — ``None`` meaning
    "exclude nothing".

    Dropping a dimension answers *"what would I get if this value were the
    selection"*, which is exactly what a click does where selecting **replaces**
    the current value (manufacturer, tech gen, player count…). Where selections
    accumulate, a click ANDs the value onto what is already chosen, so the
    dimension has to stay applied — otherwise the badge counts the value in
    isolation and promises a total the click cannot deliver (with Replay active,
    "Cash Payout (6)" landing on 0 results).

    Free when the dimension is inactive: ``model_only_models`` skips an unset
    dimension either way, so on an unfiltered request both branches build the
    same query.
    """
    return None if key in MULTI_DIMENSIONS else key


# Live rows across the Title→Model join (no variant exclusion: the candidate
# set is active Models INCLUDING Variants, which leave only by absorption).
_ACTIVE_MODELS = active_status_q("machine_models")

# Today's ``latest_year`` semantics for a Title row's sort key: active
# non-variant models only (a Variant's year must not move its Title's sort).
_SORT_YEAR_GUARD = Q(machine_models__variant_of__isnull=True) & _ACTIVE_MODELS

# Player-count buckets shown in the UI (``6`` == "6 or more"), matching the
# client's buildPlayerCountOptions. Values like 3 or 5 are foldable but unshown.
PLAYER_BUCKETS: tuple[int, ...] = (1, 2, 4, 6)


def _bucket_q(bucket: int, *, prefix: str = "") -> Q:
    """The membership predicate for a player-count bucket (``6`` == "6 or
    more"), shared by the filter and the facet count so they can't drift.

    *prefix* points the lookup at the right table: ``""`` when querying
    ``MachineModel`` directly, ``"machine_models__"`` when querying ``Title``."""
    field = f"{prefix}player_count"
    return Q(**{f"{field}__gte": 6}) if bucket >= 6 else Q(**{field: bucket})


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
    child-tagged records), walked over an in-memory *children* map — no DB hit."""
    result: set[str] = set()
    stack = [slug]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, ()))
    return frozenset(result)


def _taxonomy_expansion(
    slugs: tuple[str, ...], taxonomy: type[Theme] | type[GameplayFeature]
) -> tuple[frozenset[str], ...]:
    """Each selected slug expanded to itself + descendants (one ``frozenset``
    per selection; AND across selections, OR within one)."""
    if not slugs:
        return ()
    children = _children_map(taxonomy)
    return tuple(_descendants(slug, children) for slug in slugs)


class TaxonomyExpansion(NamedTuple):
    """The theme/feature descendant slug-sets, pre-built **once per request**
    and threaded through every queryset construction. A merged listing builds
    the ``model_only`` queryset four times (rung 1's unanimity, rung 2's
    carding, the rung-1 exclusion, Variant absorption) and the facet fan-out
    once per dimension — re-expanding at each site would scan the taxonomy
    tables ~20× per request. Free when neither dimension is active."""

    themes: tuple[frozenset[str], ...]
    features: tuple[frozenset[str], ...]


def expand_taxonomy(f: GameFilters) -> TaxonomyExpansion:
    return TaxonomyExpansion(
        themes=_taxonomy_expansion(f.themes, Theme),
        features=_taxonomy_expansion(f.features, GameplayFeature),
    )


# ---------------------------------------------------------------------------
# The dimension registry
# ---------------------------------------------------------------------------


class PathFacet(NamedTuple):
    """Facet binding for a Model-attributed value reached by ORM path (FK or
    M2M): value rows are ``(slug_path, name_path)`` pairs per candidate Model
    (``_value_rows`` in ``_game_facets.py``)."""

    # The facet's output/URL name — singular where the filter field is plural
    # ("theme" for the ``themes`` dimension); keys the payload field.
    name: str
    slug_path: str
    name_path: str


class TaxonomyFacet(NamedTuple):
    """Facet binding for a DAG taxonomy: each Model's direct tags explode to
    every ancestor value (``_hierarchical_value_rows``)."""

    name: str
    taxonomy: type[Theme] | type[GameplayFeature]
    path: str


class BucketFacet(NamedTuple):
    """Facet binding for a fixed bucket list (player count). Its value rows
    are bespoke (``_player_value_rows``); the binding marks the dimension
    counted so the registry-completeness guard sees it."""

    name: str


class EdgeFacet(NamedTuple):
    """Facet binding for the relationship keys: one option per
    ``(key, direction)`` entry of the edge vocabulary, value rows from an
    existence test per entry (``_edge_value_rows``). Option ``public_id``s are
    the wire values (``copy``, ``copy:in``); display labels are the
    frontend's."""

    name: str


FacetBinding = PathFacet | TaxonomyFacet | BucketFacet | EdgeFacet

# How one active dimension narrows the candidate Model set — chained one
# ``.filter()`` at a time from the ``MachineModel`` root (the Multi-select
# rule; see ``model_only_models``). The ``TaxonomyExpansion`` argument is the
# request's pre-built theme/feature descendant sets; most narrowers ignore it.
DimensionNarrower = Callable[
    [QuerySet[MachineModel], GameFilters, TaxonomyExpansion], QuerySet[MachineModel]
]


@dataclass(frozen=True)
class FilterDimension:
    """One Model-only filter dimension, declared once.

    The single source the narrowing chain (``model_only_models``), the
    unanimity-vacuity check (``_model_dimensions_active``), the facet fan-out
    (``_game_facets.py``) and the test vocabularies read — so a dimension
    cannot narrow the candidate set while leaving the unanimity clause
    vacuous, or count its facet against the wrong value paths. Adding a
    dimension is one ``MODEL_DIMENSION_SPECS`` entry plus its
    ``GameFilters``/wire params (and, when counted, its payload field).
    """

    key: ModelDimension
    # Whether the dimension narrows this filter set at all. Inactive means
    # "not asked", never "matches nothing".
    active: Callable[[GameFilters], bool]
    narrow: DimensionNarrower
    # ``None`` — no counted option list (``year`` is a range with bounds UI).
    facet: FacetBinding | None = None
    # Whether the /games sidebar offers a control for this dimension. A
    # non-surfaced dimension is still honored from the query string (the
    # product doc's Hidden dimensions); every current dimension is surfaced.
    surfaced: bool = True


def _narrow_player_count(
    qs: QuerySet[MachineModel], f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel]:
    if f.player_count is None:  # activeness guarantees not-None; narrows the type
        return qs
    return qs.filter(_bucket_q(f.player_count))


def _narrow_year(
    qs: QuerySet[MachineModel], f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel]:
    if f.year_min is not None:
        qs = qs.filter(year__gte=f.year_min)
    if f.year_max is not None:
        qs = qs.filter(year__lte=f.year_max)
    return qs


def _narrow_themes(
    qs: QuerySet[MachineModel], f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel]:
    for descendants in expansion.themes:
        qs = qs.filter(themes__slug__in=descendants)
    return qs


def _narrow_features(
    qs: QuerySet[MachineModel], f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel]:
    for descendants in expansion.features:
        qs = qs.filter(gameplay_features__slug__in=descendants)
    return qs


def _narrow_reward_types(
    qs: QuerySet[MachineModel], f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel]:
    for slug in f.reward_types:
        qs = qs.filter(reward_types__slug=slug)
    return qs


def _narrow_edge(
    qs: QuerySet[MachineModel], f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel]:
    """Each selection is an existence predicate ANDed on (a Model can be both
    a copy and a conversion). An unknown or malformed value matches nothing —
    the nonexistent-tag feel, not a validation error."""
    for value in f.edge:
        selection = parse_edge_value(value)
        if selection is None:
            return qs.none()
        qs = qs.filter(edge_q(selection))
    return qs


MODEL_DIMENSION_SPECS: Final[Mapping[ModelDimension, FilterDimension]] = {
    spec.key: spec
    for spec in (
        FilterDimension(
            key="manufacturer",
            active=lambda f: bool(f.manufacturer),
            narrow=lambda qs, f, expansion: qs.filter(
                corporate_entity__manufacturer__slug=f.manufacturer
            ),
            facet=PathFacet(
                "manufacturer",
                "corporate_entity__manufacturer__slug",
                "corporate_entity__manufacturer__name",
            ),
        ),
        FilterDimension(
            key="person",
            active=lambda f: bool(f.person),
            narrow=lambda qs, f, expansion: qs.filter(credits__person__slug=f.person),
            facet=PathFacet("person", "credits__person__slug", "credits__person__name"),
        ),
        FilterDimension(
            key="tech_gen",
            active=lambda f: bool(f.tech_gen),
            narrow=lambda qs, f, expansion: qs.filter(
                technology_generation__slug=f.tech_gen
            ),
            facet=PathFacet(
                "tech_gen", "technology_generation__slug", "technology_generation__name"
            ),
        ),
        FilterDimension(
            key="display_type",
            active=lambda f: bool(f.display_type),
            narrow=lambda qs, f, expansion: qs.filter(
                display_type__slug=f.display_type
            ),
            facet=PathFacet("display_type", "display_type__slug", "display_type__name"),
        ),
        FilterDimension(
            key="system",
            active=lambda f: bool(f.system),
            narrow=lambda qs, f, expansion: qs.filter(system__slug=f.system),
            facet=PathFacet("system", "system__slug", "system__name"),
        ),
        FilterDimension(
            key="player_count",
            active=lambda f: f.player_count is not None,
            narrow=_narrow_player_count,
            facet=BucketFacet("player_count"),
        ),
        FilterDimension(
            key="year",
            active=lambda f: f.year_min is not None or f.year_max is not None,
            narrow=_narrow_year,
        ),
        FilterDimension(
            key="themes",
            active=lambda f: bool(f.themes),
            narrow=_narrow_themes,
            facet=TaxonomyFacet("theme", Theme, "themes"),
        ),
        FilterDimension(
            key="features",
            active=lambda f: bool(f.features),
            narrow=_narrow_features,
            facet=TaxonomyFacet("feature", GameplayFeature, "gameplay_features"),
        ),
        FilterDimension(
            key="reward_types",
            active=lambda f: bool(f.reward_types),
            narrow=_narrow_reward_types,
            facet=PathFacet("reward_type", "reward_types__slug", "reward_types__name"),
        ),
        FilterDimension(
            key="edge",
            active=lambda f: bool(f.edge),
            narrow=_narrow_edge,
            facet=EdgeFacet("edge"),
        ),
        # The hidden dimensions (the product doc's Hidden dimensions): honored
        # from the query string so a dimension detail page can pin the listing,
        # but surfaced=False — no sidebar control — and facet=None — no counts.
        FilterDimension(
            key="display_subtype",
            active=lambda f: bool(f.display_subtype),
            narrow=lambda qs, f, expansion: qs.filter(
                display_subtype__slug=f.display_subtype
            ),
            surfaced=False,
        ),
        FilterDimension(
            key="tag",
            active=lambda f: bool(f.tag),
            narrow=lambda qs, f, expansion: qs.filter(tags__slug=f.tag),
            surfaced=False,
        ),
        FilterDimension(
            key="technology_subgeneration",
            active=lambda f: bool(f.technology_subgeneration),
            # A Model belongs to a subgeneration directly or through its
            # system — the OR mirrors the /api/models/ narrower, whose two
            # arms both matter (a WPC game rarely re-declares its system's
            # subgeneration on the Model row).
            narrow=lambda qs, f, expansion: qs.filter(
                Q(technology_subgeneration__slug=f.technology_subgeneration)
                | Q(system__technology_subgeneration__slug=f.technology_subgeneration)
            ),
            surfaced=False,
        ),
        FilterDimension(
            key="cabinet",
            active=lambda f: bool(f.cabinet),
            narrow=lambda qs, f, expansion: qs.filter(cabinet__slug=f.cabinet),
            surfaced=False,
        ),
        FilterDimension(
            key="game_format",
            active=lambda f: bool(f.game_format),
            narrow=lambda qs, f, expansion: qs.filter(game_format__slug=f.game_format),
            surfaced=False,
        ),
        FilterDimension(
            key="production_status",
            active=lambda f: bool(f.production_status),
            narrow=lambda qs, f, expansion: qs.filter(
                production_status__slug=f.production_status
            ),
            surfaced=False,
        ),
        FilterDimension(
            key="corporate_entity",
            active=lambda f: bool(f.corporate_entity),
            narrow=lambda qs, f, expansion: qs.filter(
                corporate_entity__slug=f.corporate_entity
            ),
            surfaced=False,
        ),
    )
}

# A Literal proves key validity, not completeness or order — this does, at
# import time. Order is pinned (not just the key set) so the chained filters
# hit the SQL in the vocabulary's declared order, keeping query shape
# deterministic across registry edits.
assert tuple(MODEL_DIMENSION_SPECS) == MODEL_DIMENSIONS


# ---------------------------------------------------------------------------
# The two sets
# ---------------------------------------------------------------------------


def model_only_models(
    f: GameFilters,
    *,
    exclude: ModelDimension | None = None,
    expansion: TaxonomyExpansion | None = None,
) -> QuerySet[MachineModel]:
    """Active Models (Variants included) passing every **Model-only** dimension
    except *exclude* — the set unanimity is measured over.

    Dimensions are chained one ``.filter()`` at a time from the ``MachineModel``
    root, so every dimension lands on the *same* Model row — a single Model must
    satisfy everything (the Multi-select rule). Missing values fail: a Model
    with no year matches no year range.

    *expansion* is the once-per-request taxonomy expansion; entry points build
    it once and thread it, standalone calls may omit it.
    """
    if expansion is None:
        expansion = expand_taxonomy(f)
    # The Title must be live too: ``restore_model`` deliberately leaves a
    # deleted parent Title untouched, so an active Model under a deleted Title
    # is a reachable state — it must not card or count. (The Title-grain
    # listing got this for free by rooting at ``Title.objects.active()``.)
    qs: QuerySet[MachineModel] = MachineModel.objects.active().filter(
        active_status_q("title")
    )
    for key, spec in MODEL_DIMENSION_SPECS.items():
        if spec.active(f) and exclude != key:
            qs = spec.narrow(qs, f, expansion)
    return qs


def _name_match_q(q: str) -> Q:
    """Folded substring predicate on the record's own ``name`` — Postgres
    de-accents both sides (``__unaccent__``), SQLite falls back to plain
    ``icontains`` (the existing dev/prod search gap)."""
    if connection.vendor == "postgresql":
        return Q(name__unaccent__icontains=_fold(q))
    return Q(name__icontains=q)


def model_match_q(q: str) -> Q:
    """The record-local shared class at the ``MachineModel`` root: own name or
    own abbreviation. The abbreviation arm is an ``Exists`` so the predicate is
    single-valued (a join ``Q`` would duplicate rows per matching row)."""
    return _name_match_q(q) | Q(
        Exists(
            ModelAbbreviation.objects.filter(
                machine_model=OuterRef("pk"), value__icontains=q
            )
        )
    )


def title_own_match_q(q: str) -> Q:
    """The record-local shared class at the ``Title`` root: own name or own
    abbreviation. Single-valued for the same reason as :func:`model_match_q`."""
    return _name_match_q(q) | Q(
        Exists(
            TitleAbbreviation.objects.filter(title=OuterRef("pk"), value__icontains=q)
        )
    )


def carding_models(
    f: GameFilters,
    *,
    exclude: ModelDimension | None = None,
    expansion: TaxonomyExpansion | None = None,
) -> QuerySet[MachineModel]:
    """:func:`model_only_models` plus the record-local shared class — the set a
    Model must be in to card (rung 2) or to absorb its Variants (rung 3).

    One queryset built on top of the other, so the two cannot disagree; with no
    ``q`` active they are the same set. The shared class is never an *exclude*
    key — no facet excludes or counts ``q``.
    """
    qs = model_only_models(f, exclude=exclude, expansion=expansion)
    q = f.q.strip()
    if q:
        qs = qs.filter(model_match_q(q))
    return qs


def _title_only_q(
    f: GameFilters, *, prefix: str = "", exclude: TitleDimension | None = None
) -> Q:
    """The Title-only dimensions (franchise, series), rooted at ``Title``
    (``prefix=""``) or reached from a Model row (``prefix="title__"``).
    *exclude* drops one dimension for its own facet's N-1 base — series still
    binds while franchise is being counted, and vice versa."""
    qq = Q()
    if f.franchise and exclude != "franchise":
        qq &= Q(**{f"{prefix}franchise__slug": f.franchise})
    if f.series and exclude != "series":
        qq &= Q(**{f"{prefix}series__slug": f.series})
    return qq


# ---------------------------------------------------------------------------
# The three rungs
# ---------------------------------------------------------------------------


def _model_dimensions_active(f: GameFilters) -> bool:
    """Whether any **Model-only** dimension narrows the candidate set. ``q``
    (record-local shared) and franchise/series (Title-only) are not among
    them. Reads ``MODEL_DIMENSION_SPECS``, so a new dimension can't narrow
    the candidate set while leaving rung 1's unanimity clause vacuous."""
    return any(spec.active(f) for spec in MODEL_DIMENSION_SPECS.values())


def title_rows_qs(
    f: GameFilters, *, expansion: TaxonomyExpansion | None = None
) -> QuerySet[Title]:
    """Rung 1 — Titles that card: the Title-only dimensions hold, the Title's
    own record-local shared values match and — only when a Model-only dimension
    is active — every live Model is in :func:`model_only_models`, with at least
    one to be unanimous about.

    The unanimity clause is conditional deliberately. With no Model-only
    dimension active it is vacuous, and an active Title with **zero** live
    Models still cards — the listing supports empty Titles (deleting the last
    Model orphans one; the API tests pin it). Under an active Model-only
    dimension the ``n_models > 0`` guard is what keeps vacuous truth from
    carding an empty Title for a manufacturer it never had. Skipping the
    aggregates entirely also makes the hottest path — the unfiltered listing —
    a plain active-Titles query."""
    qs = Title.objects.active().filter(_title_only_q(f))
    q = f.q.strip()
    if q:
        qs = qs.filter(title_own_match_q(q))
    if not _model_dimensions_active(f):
        return qs
    return qs.annotate(
        n_models=Count("machine_models", filter=_ACTIVE_MODELS, distinct=True),
        n_match=Count(
            "machine_models",
            filter=_ACTIVE_MODELS
            & Q(machine_models__in=model_only_models(f, expansion=expansion)),
            distinct=True,
        ),
    ).filter(n_models__gt=0, n_match=F("n_models"))


def model_rows_qs(
    f: GameFilters, *, expansion: TaxonomyExpansion | None = None
) -> QuerySet[MachineModel]:
    """Rungs 2 and 3 — Models that card: in :func:`carding_models`, their Title
    did not card, their Title satisfies every Title-only dimension (the binding
    half of the Title-only class), and — for a Variant — the parent Model is
    not itself in ``carding`` (absorption)."""
    if expansion is None:
        expansion = expand_taxonomy(f)
    carding = carding_models(f, expansion=expansion)
    rows = carding.filter(_title_only_q(f, prefix="title__"))
    rows = rows.exclude(title__in=title_rows_qs(f, expansion=expansion).values("pk"))
    # Explicit two-arm Q: ``exclude(variant_of__in=…)`` alone would lean on
    # NULL semantics for non-variants; this spells "is a Variant AND parent
    # absorbed it".
    return rows.exclude(
        Q(variant_of__isnull=False)
        & Q(variant_of__in=carding_models(f, expansion=expansion))
    )


# ---------------------------------------------------------------------------
# Rows at card grain
# ---------------------------------------------------------------------------


class GameRow(NamedTuple):
    """One listing row at card grain — the ordering/pagination shape, hydrated
    later by ``(kind, pk)``. ``kind`` carries the entity_type ClassVar values
    (``"title"`` / ``"model"``), never a re-spelled literal."""

    kind: str
    pk: int
    sort_year: int | None
    name: str


class GameRowValues(TypedDict):
    """What the two ``.values("kind", "pk", "sort_year", "name")`` row querysets
    yield (:class:`GameRow` is the tuple view the merge converts into)."""

    kind: str
    pk: int
    sort_year: int | None
    name: str


def _title_value_rows(
    f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[Title, GameRowValues]:
    """Rung-1 rows as ``.values()`` with the literal discriminator and the sort
    key selected."""
    return (
        title_rows_qs(f, expansion=expansion)
        # Clear the model's default ``ordering = ["name"]`` — the merge sorts
        # in Python, so an SQL ORDER BY is pure waste.
        .order_by()
        .annotate(
            kind=Value(Title.entity_type, output_field=CharField()),
            sort_year=Max("machine_models__year", filter=_SORT_YEAR_GUARD),
        )
        .values("kind", "pk", "sort_year", "name")
    )


def _model_value_rows(
    f: GameFilters, expansion: TaxonomyExpansion
) -> QuerySet[MachineModel, GameRowValues]:
    """Rung-2/3 rows in the same shape (the Model's own year is its sort key).

    ``.distinct()`` because the theme dimension chains M2M joins that duplicate
    a Model's row; the Title side needs none (its aggregates force a
    one-row-per-Title ``GROUP BY``)."""
    return (
        model_rows_qs(f, expansion=expansion)
        .order_by()  # clear default ordering — the merge sorts in Python
        .annotate(
            kind=Value(MachineModel.entity_type, output_field=CharField()),
            sort_year=F("year"),
        )
        .distinct()
        .values("kind", "pk", "sort_year", "name")
    )


def _merge_key(row: GameRow) -> tuple[bool, int, str, str, str, int]:
    """The listing order: newest first, nulls last, then name (folded — case-
    and diacritic-insensitive), kind, pk. The ``kind``/``pk`` tail is the
    tie-break that gives offset pagination a total order.

    Folding is deliberate: a raw code-point sort puts every lowercase name
    after every uppercase one and every accented initial after ``z``. Folded
    Python ordering is also backend-independent, where an SQL sort inherits
    each backend's collation (Postgres ``en_US`` ignores spaces: "De Luxe"
    after "Deluxe"; SQLite is code-point BINARY)."""
    return (
        row.sort_year is None,
        -(row.sort_year or 0),
        _fold(row.name),
        row.name,
        row.kind,
        row.pk,
    )


def game_rows_merged(f: GameFilters) -> list[GameRow]:
    """The listing rows: two queries, merged and ordered in Python.
    Materializes every matching row's four columns (bounded by the catalog:
    ~6.2k Titles + shards), the ``_count_manufacturer`` precedent. ``count``
    is the list's length."""
    expansion = expand_taxonomy(f)
    rows = [GameRow(**r) for r in _title_value_rows(f, expansion)]
    rows += [GameRow(**r) for r in _model_value_rows(f, expansion)]
    rows.sort(key=_merge_key)
    return rows
