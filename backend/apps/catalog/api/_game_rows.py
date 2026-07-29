"""Card-grain listing rows — the Title ➡ Model ➡ Variant roll-up engine.

The proving core for the heterogeneous listing
(docs/plans/filtering_and_search/ModelFilteringPlan.md, COMMIT.HET.PROVE):
one row per *card*, where a card is a Title when every one of its live Models
matches the Model-only dimensions (rung 1), else one card per matching Model
(rung 2), with a Variant absorbed into a matching parent (rung 3).

Deliberately unwired from any route: no serialization, no wire contract. The
facet fan-out at card grain lives in ``_game_facets.py``, built on this
module's two sets and rungs. The filter vocabulary is the full listing set,
by semantics class:

- ``manufacturer`` / ``person`` / ``tech_gen`` / ``display_type`` / ``system``
  — single-valued Model-only
- ``player_count`` — bucketed Model-only (``6`` means "6 or more", via the
  shared ``_bucket_q``)
- ``themes`` / ``features`` — multi-select Model-only (AND of ORs,
  descendant-expanded)
- ``reward_types`` — multi-select Model-only (AND, no hierarchy)
- ``year_min``/``year_max`` — range, Model-only
- ``franchise`` / ``series`` — Title-only, binding all of a Title's Models
- ``q`` — the record-local shared class (name + abbreviations), tested on the
  record being decided and propagating in neither direction

The two-set split is the engine's load-bearing invariant: **unanimity is
measured over** :func:`model_only_models` **(Model-only dimensions alone),
never over** :func:`carding_models` **(that plus the shared class)**. Feeding
``carding`` into the unanimity count silently inverts the product doc's worked
examples (``q=Ice Fever`` would return the Ice Fever Model where the Title
card is specified) — a plausible-looking wrong answer, not an error.

Rows come from :func:`game_rows_merged` — two queries merged and ordered in
Python (the ``_count_manufacturer`` precedent: ~7k-row scan + rollup). The
proving commit also carried a ``.union()`` seam; the merge won on the benchmark
(the union ran the whole row algebra twice per request, once for the page and
once for ``count``) and the union was deleted when the seam was wired. The
decision and the findings that outlive the code — the compound-arm ORDER BY
rules, the collation divergence, the Railway re-measurement instructions — are
recorded in ModelFilteringPlan.md's proving answers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple, TypedDict, get_args

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
]
TitleDimension = Literal["franchise", "series"]

# The Model-only dimension keys, for N-1 facet exclusion — derived from the
# Literal so the runtime tuple and the type can't diverge. ``q`` is the
# record-local shared class and ``franchise``/``series`` are Title-only; none
# of the three is a Model-only dimension.
MODEL_DIMENSIONS: tuple[ModelDimension, ...] = get_args(ModelDimension)

# Whether each Model-only dimension is active on a filter set — the single
# source read by the narrowing chain (``model_only_models``) and the
# unanimity-vacuity check (``_model_dimensions_active``), so the two can't
# drift when a dimension is added.
_DIMENSION_ACTIVE: Final[Mapping[ModelDimension, Callable[[GameFilters], bool]]] = {
    "manufacturer": lambda f: bool(f.manufacturer),
    "person": lambda f: bool(f.person),
    "tech_gen": lambda f: bool(f.tech_gen),
    "display_type": lambda f: bool(f.display_type),
    "system": lambda f: bool(f.system),
    "player_count": lambda f: f.player_count is not None,
    "year": lambda f: f.year_min is not None or f.year_max is not None,
    "themes": lambda f: bool(f.themes),
    "features": lambda f: bool(f.features),
    "reward_types": lambda f: bool(f.reward_types),
}

# A Literal proves key validity, not completeness — this does, at import time.
assert set(_DIMENSION_ACTIVE) == set(MODEL_DIMENSIONS)

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
    qs = MachineModel.objects.active().filter(active_status_q("title"))

    def on(key: ModelDimension) -> bool:
        return _DIMENSION_ACTIVE[key](f) and exclude != key

    if on("manufacturer"):
        qs = qs.filter(corporate_entity__manufacturer__slug=f.manufacturer)
    if on("person"):
        qs = qs.filter(credits__person__slug=f.person)
    if on("tech_gen"):
        qs = qs.filter(technology_generation__slug=f.tech_gen)
    if on("display_type"):
        qs = qs.filter(display_type__slug=f.display_type)
    if on("system"):
        qs = qs.filter(system__slug=f.system)
    if on("player_count") and f.player_count is not None:  # None check narrows
        qs = qs.filter(_bucket_q(f.player_count))
    if on("year"):
        if f.year_min is not None:
            qs = qs.filter(year__gte=f.year_min)
        if f.year_max is not None:
            qs = qs.filter(year__lte=f.year_max)
    if on("themes"):
        for descendants in expansion.themes:
            qs = qs.filter(themes__slug__in=descendants)
    if on("features"):
        for descendants in expansion.features:
            qs = qs.filter(gameplay_features__slug__in=descendants)
    if on("reward_types"):
        for slug in f.reward_types:
            qs = qs.filter(reward_types__slug=slug)
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
    them. Reads the ``_DIMENSION_ACTIVE`` registry, so a new dimension can't
    narrow the candidate set while leaving rung 1's unanimity clause vacuous."""
    return any(active(f) for active in _DIMENSION_ACTIVE.values())


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
