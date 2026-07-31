"""The facet fan-out at card grain — every sidebar badge counts *cards*.

One cell algebra serves every counted dimension, over the two sets and rungs
``_game_rows.py`` defines:
per dimension, group the matching Models by facet value and Title, compare each
(value, Title) cell against that Title's live-Model total, tally a unanimous
Title as one card and a shattered one as one card per matching Model, less
Variants absorbed by a matching parent.

Shared across the whole fan-out (computed once per request):

- the live-Model total per Title (the unanimity denominator) — one grouped
  query over the Model table, shared by every dimension's fan-out;
- the Titles passing their own record-local shared values (``q``);
- the Models passing the shared class (``q``) — dimension-independent, so one
  query serves every dimension's carding test.

The two-set split survives here: unanimity is read off the value rows, which
come from ``model_only_models(exclude=<dimension>)``, while a Model contributes
a card only if it also passes the shared class. Counting both off one set makes
every badge disagree with the result page for exactly the queries the split
exists to get right.

Two facet shapes need more than that algebra:

- **Title-only dimensions** (franchise, series) group the same per-Title cells
  by the Title's own value. When no Model-only dimension is active, rung 1's
  unanimity clause is vacuous and the carded set comes from a Title-grain query
  instead — which is what lets an *empty* Title (zero live Models) keep its
  badge, matching the rows engine.
- **Hierarchical dimensions** (theme, feature) explode each Model's direct tags
  to every ancestor value in Python (the ``_count_hierarchical`` precedent) —
  a Model tagged under a child contributes to the parent's tally too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from django.db.models import Count

from apps.core.models import active_status_q

from ..engine.query.facet_helpers import (
    FacetOption,
    ancestor_map,
    with_selected,
)
from ..models import (
    Cabinet,
    DisplayType,
    Franchise,
    GameFormat,
    GameplayFeature,
    MachineModel,
    Manufacturer,
    Person,
    ProductionStatus,
    RewardType,
    Series,
    System,
    TechnologyGeneration,
    Theme,
    Title,
)
from ._edge_vocabulary import (
    EDGE_DIRECTIONS,
    EDGE_KEYS,
    EdgeSelection,
    edge_q,
    edge_wire_value,
)
from ._game_rows import (
    MODEL_DIMENSION_SPECS,
    PLAYER_BUCKETS,
    UNCLASSIFIED,
    EdgeFacet,
    GameFilters,
    ModelDimension,
    PathFacet,
    SparseFacet,
    TaxonomyExpansion,
    TaxonomyFacet,
    TitleDimension,
    _model_dimensions_active,
    _title_only_q,
    carding_models,
    expand_taxonomy,
    facet_exclude,
    model_only_models,
    title_own_match_q,
)

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


# dataclass, not NamedTuple: a NamedTuple field named ``count`` would shadow
# tuple.count and mypy rejects it.
@dataclass(frozen=True)
class PlayerCountOption:
    """A player-count bucket (the ``6`` bucket means "6 or more")."""

    value: int
    count: int


@dataclass(frozen=True)
class GameFacetOptions:
    """The full set of sidebar option lists at card grain — value-pruned,
    counted, active selections re-included at zero. Field names use the
    frontend/URL facet vocabulary (singular)."""

    manufacturer: list[FacetOption] = field(default_factory=list)
    person: list[FacetOption] = field(default_factory=list)
    tech_gen: list[FacetOption] = field(default_factory=list)
    display_type: list[FacetOption] = field(default_factory=list)
    system: list[FacetOption] = field(default_factory=list)
    reward_type: list[FacetOption] = field(default_factory=list)
    edge: list[FacetOption] = field(default_factory=list)
    # The sparse dimensions: option lists are real vocabulary values only
    # (never UNCLASSIFIED); the default value's count is the null-folded one.
    cabinet: list[FacetOption] = field(default_factory=list)
    game_format: list[FacetOption] = field(default_factory=list)
    production_status: list[FacetOption] = field(default_factory=list)
    theme: list[FacetOption] = field(default_factory=list)
    feature: list[FacetOption] = field(default_factory=list)
    franchise: list[FacetOption] = field(default_factory=list)
    series: list[FacetOption] = field(default_factory=list)
    player_count: list[PlayerCountOption] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The cell algebra
# ---------------------------------------------------------------------------


class _FacetCell(NamedTuple):
    """One (facet value, Title) cell of the rollup — the key the matching
    tallies and the carded set share, for every dimension shape."""

    value_slug: str
    title_id: int


class _FacetValueRow(NamedTuple):
    """One (Model, facet value) pair of a dimension's candidate set — the rows
    every shape reduces to before the shared tally. Rows are distinct per
    ``(pk, value_slug)``; a Model may carry several values (person, reward
    types, exploded taxonomy ancestors) and then appears once per value."""

    pk: int
    title_id: int
    variant_of_id: int | None
    value_slug: str
    value_name: str


class _SharedFanout(NamedTuple):
    """The per-request inputs every dimension's tally shares — including the
    taxonomy expansion, so the fan-out's ~13 queryset constructions never
    re-scan the taxonomy tables.

    ``own_q_titles`` / ``q_match_models`` are ``None`` when no ``q`` is active,
    meaning every record passes the shared class."""

    totals_by_title: dict[int, int]
    own_q_titles: set[int] | None
    q_match_models: set[int] | None
    expansion: TaxonomyExpansion


def _shared_fanout(f: GameFilters) -> _SharedFanout:
    expansion = expand_taxonomy(f)
    # Live Models under live Titles — the same liveness rule as the candidate
    # set, so a deleted Title's live Models neither total nor match.
    totals_by_title = dict(
        MachineModel.objects.active()
        .filter(active_status_q("title"))
        .values_list("title_id")
        .annotate(total=Count("pk"))
    )
    q = f.q.strip()
    if not q:
        return _SharedFanout(totals_by_title, None, None, expansion)
    own_q_titles = set(
        Title.objects.active().filter(title_own_match_q(q)).values_list("pk", flat=True)
    )
    # The shared class is dimension-independent, so the q-passing Model set is
    # computed once and reused as every dimension's carding test — equivalent to
    # ``carding_models(f, exclude=<dim>)`` intersected with that dimension's
    # value rows, which already come from ``model_only_models(exclude=<dim>)``.
    q_match_models = set(
        carding_models(GameFilters(q=f.q)).values_list("pk", flat=True)
    )
    return _SharedFanout(totals_by_title, own_q_titles, q_match_models, expansion)


def _unanimous_cells(
    rows: list[_FacetValueRow], shared: _SharedFanout
) -> set[_FacetCell]:
    """Cells whose value covers the Title: every live Model matches (the rows
    are the matching Models), and the Title passes its own shared values."""
    matching: dict[_FacetCell, int] = {}
    for r in rows:
        cell = _FacetCell(r.value_slug, r.title_id)
        matching[cell] = matching.get(cell, 0) + 1
    return {
        cell
        for cell, n in matching.items()
        if n == shared.totals_by_title.get(cell.title_id, 0)
        and (shared.own_q_titles is None or cell.title_id in shared.own_q_titles)
    }


def _tally_options(
    rows: list[_FacetValueRow],
    carded: set[_FacetCell],
    names: dict[str, str],
    shared: _SharedFanout,
) -> list[FacetOption]:
    """The shared tally: one card per carded cell, plus one per carding Model
    in an uncarded cell, less Variants absorbed by a matching parent."""
    tally: dict[str, int] = {}
    for cell in carded:
        tally[cell.value_slug] = tally.get(cell.value_slug, 0) + 1

    carding_rows = [
        r
        for r in rows
        if shared.q_match_models is None or r.pk in shared.q_match_models
    ]
    carding_pks_by_value: dict[str, set[int]] = {}
    for r in carding_rows:
        carding_pks_by_value.setdefault(r.value_slug, set()).add(r.pk)
    for r in carding_rows:
        if _FacetCell(r.value_slug, r.title_id) in carded:
            continue
        if (
            r.variant_of_id is not None
            and r.variant_of_id in carding_pks_by_value[r.value_slug]
        ):
            continue  # rung 3: absorbed by a matching parent
        tally[r.value_slug] = tally.get(r.value_slug, 0) + 1

    options = [
        FacetOption(slug, names[slug], count)
        for slug, count in tally.items()
        if count > 0
    ]
    options.sort(key=lambda o: o.name)
    return options


# ---------------------------------------------------------------------------
# Value rows per dimension shape
# ---------------------------------------------------------------------------


def _value_rows(
    f: GameFilters,
    shared: _SharedFanout,
    dimension: ModelDimension,
    binding: PathFacet,
) -> tuple[list[_FacetValueRow], dict[str, str]]:
    """Value rows for a Model-attributed dimension (FK or M2M): each candidate
    Model paired with each of its values, over the base :func:`facet_exclude`
    picks for *dimension* — N-1 where a selection replaces, the full set where
    selections accumulate. ``.distinct()`` collapses join duplicates (two
    credits by one person)."""
    gate = _title_only_q(f, prefix="title__")
    # ``.filter(isnull=False)``, never ``.exclude(isnull=True)``: on a
    # multivalued path (credits, reward_types) exclude compiles to a NOT-IN
    # subquery that benchmarked more than an order of magnitude slower, where
    # filter is a plain join condition.
    raw = (
        model_only_models(
            f, exclude=facet_exclude(dimension), expansion=shared.expansion
        )
        .filter(gate)
        .filter(**{f"{binding.slug_path}__isnull": False})
        .values_list(
            "pk", "title_id", "variant_of_id", binding.slug_path, binding.name_path
        )
        .distinct()
    )
    rows = [_FacetValueRow(*r) for r in raw]
    names: dict[str, str] = {}
    for r in rows:
        names.setdefault(r.value_slug, r.value_name)
    return rows, names


def _hierarchical_value_rows(
    f: GameFilters,
    shared: _SharedFanout,
    dimension: ModelDimension,
    binding: TaxonomyFacet,
) -> tuple[list[_FacetValueRow], dict[str, str]]:
    """Value rows for a taxonomy dimension: each Model's direct tags exploded
    to every ancestor value, de-duplicated per ``(pk, value)`` — the DAG can
    reach one ancestor twice. Base per :func:`facet_exclude`, as in
    :func:`_value_rows`; themes and features accumulate, so theirs stays
    applied."""
    ancestors = ancestor_map(binding.taxonomy, "slug", "parents__slug")
    names: dict[str, str] = dict(
        binding.taxonomy._default_manager.values_list("slug", "name")
    )
    gate = _title_only_q(f, prefix="title__")
    raw = (
        model_only_models(
            f, exclude=facet_exclude(dimension), expansion=shared.expansion
        )
        .filter(gate)
        # filter, not exclude — see _value_rows on multivalued isnull.
        .filter(**{f"{binding.path}__slug__isnull": False})
        .values_list("pk", "title_id", "variant_of_id", f"{binding.path}__slug")
        .distinct()
    )
    seen: set[tuple[int, str]] = set()
    rows: list[_FacetValueRow] = []
    for pk, title_id, variant_of_id, leaf in raw:
        if leaf is None:  # excluded above; narrows the type
            continue
        ancestor_slugs: set[str] = ancestors.get(leaf, {leaf})
        for slug in ancestor_slugs:
            if (pk, slug) in seen:
                continue
            seen.add((pk, slug))
            rows.append(
                _FacetValueRow(pk, title_id, variant_of_id, slug, names.get(slug, slug))
            )
    return rows, names


def _edge_value_rows(
    f: GameFilters, shared: _SharedFanout
) -> tuple[list[_FacetValueRow], dict[str, str]]:
    """Value rows for the relationship keys: one existence-filtered query per
    ``(key, direction)`` entry over the candidate set (accumulating dimension,
    so the base keeps the current edge selections — :func:`facet_exclude`).
    Rows are distinct Models per entry, so a Model carrying two edges of one
    kind counts once; a Model satisfying two entries counts once under each.

    ``value_slug`` and ``value_name`` are both the wire value (``copy:in``) —
    reader-facing labels live in the frontend's relationship vocabulary, not
    here."""
    gate = _title_only_q(f, prefix="title__")
    base = model_only_models(
        f, exclude=facet_exclude("edge"), expansion=shared.expansion
    ).filter(gate)
    rows: list[_FacetValueRow] = []
    names: dict[str, str] = {}
    for key in EDGE_KEYS:
        for direction in EDGE_DIRECTIONS:
            wire = edge_wire_value(EdgeSelection(key, direction))
            raw = (
                base.filter(edge_q(EdgeSelection(key, direction)))
                .values_list("pk", "title_id", "variant_of_id")
                .distinct()
            )
            for pk, title_id, variant_of_id in raw:
                rows.append(_FacetValueRow(pk, title_id, variant_of_id, wire, wire))
            names[wire] = wire
    return rows, names


def _sparse_value_rows(
    f: GameFilters,
    shared: _SharedFanout,
    dimension: ModelDimension,
    binding: SparseFacet,
    default_slug: str,
) -> tuple[list[_FacetValueRow], dict[str, str]]:
    """Value rows for a sparse dimension: **every** candidate Model paired
    with its single value, a null FK folded into *default_slug*. Names
    resolve from the vocabulary table — a folded null row carries none — and
    a missing default row degrades to the raw slug rather than raising."""
    names: dict[str, str] = dict(
        binding.vocabulary._default_manager.values_list("slug", "name")
    )
    names.setdefault(default_slug, default_slug)
    gate = _title_only_q(f, prefix="title__")
    raw = (
        model_only_models(
            f, exclude=facet_exclude(dimension), expansion=shared.expansion
        )
        .filter(gate)
        .values_list("pk", "title_id", "variant_of_id", f"{binding.path}__slug")
        .distinct()
    )
    rows: list[_FacetValueRow] = []
    for pk, title_id, variant_of_id, slug in raw:
        value = slug if slug is not None else default_slug
        rows.append(
            _FacetValueRow(pk, title_id, variant_of_id, value, names.get(value, value))
        )
    return rows, names


def _player_value_rows(f: GameFilters, shared: _SharedFanout) -> list[_FacetValueRow]:
    """Value rows for the player-count buckets: each counted Model mapped to
    its bucket (``6`` collects 6-or-more; values outside ``PLAYER_BUCKETS``
    fold nowhere, mirroring ``_bucket_q``'s exact-match buckets)."""
    gate = _title_only_q(f, prefix="title__")
    raw = (
        model_only_models(
            f, exclude=facet_exclude("player_count"), expansion=shared.expansion
        )
        .filter(gate)
        .filter(player_count__isnull=False)
        .values_list("pk", "title_id", "variant_of_id", "player_count")
        .distinct()
    )
    rows: list[_FacetValueRow] = []
    for pk, title_id, variant_of_id, count in raw:
        if count is None:  # excluded above; narrows the type
            continue
        bucket = 6 if count >= 6 else count
        if bucket not in PLAYER_BUCKETS:
            continue
        rows.append(
            _FacetValueRow(pk, title_id, variant_of_id, str(bucket), str(bucket))
        )
    return rows


def _title_dimension_value_rows(
    f: GameFilters, shared: _SharedFanout, exclude: TitleDimension, fk: str
) -> tuple[list[_FacetValueRow], dict[str, str]]:
    """Value rows for a Title-only dimension: each candidate Model paired with
    its Title's value. The title gate drops the dimension's own arm (series
    still binds while franchise is counted)."""
    gate = _title_only_q(f, prefix="title__", exclude=exclude)
    raw = (
        model_only_models(f, expansion=shared.expansion)
        .filter(gate)
        .filter(**{f"title__{fk}__isnull": False})
        .values_list(
            "pk",
            "title_id",
            "variant_of_id",
            f"title__{fk}__slug",
            f"title__{fk}__name",
        )
        .distinct()
    )
    rows = [_FacetValueRow(*r) for r in raw]
    names: dict[str, str] = {}
    for r in rows:
        names.setdefault(r.value_slug, r.value_name)
    return rows, names


def _vacuous_title_cells(
    f: GameFilters, exclude: TitleDimension, fk: str
) -> tuple[set[_FacetCell], dict[str, str]]:
    """The carded cells of a Title-only dimension when no Model-only dimension
    is active: rung 1's unanimity clause is vacuous, so *every* Title carrying
    the value and passing its own shared values cards — including Titles with
    zero live Models, which have no value rows and would otherwise vanish."""
    qs = Title.objects.active().filter(_title_only_q(f, exclude=exclude))
    q = f.q.strip()
    if q:
        qs = qs.filter(title_own_match_q(q))
    cells: set[_FacetCell] = set()
    names: dict[str, str] = {}
    for slug, name, pk in qs.exclude(**{f"{fk}__isnull": True}).values_list(
        f"{fk}__slug", f"{fk}__name", "pk"
    ):
        cells.add(_FacetCell(slug, pk))
        names.setdefault(slug, name)
    return cells, names


# ---------------------------------------------------------------------------
# Per-dimension assembly
# ---------------------------------------------------------------------------


def _counted_facets(
    f: GameFilters, shared: _SharedFanout
) -> dict[str, list[FacetOption]]:
    """Options for every Model dimension carrying a countable facet binding,
    keyed by the binding's facet name — the value-rows shape is dispatched
    from the registry, so a dimension cannot count against the wrong paths.
    Bucket facets (player count) have a bespoke output type and are assembled
    by :func:`_player_facet`; ``facet=None`` dimensions (year) count nothing."""
    counted: dict[str, list[FacetOption]] = {}
    for spec in MODEL_DIMENSION_SPECS.values():
        match spec.facet:
            case PathFacet() as binding:
                rows, names = _value_rows(f, shared, spec.key, binding)
            case TaxonomyFacet() as binding:
                rows, names = _hierarchical_value_rows(f, shared, spec.key, binding)
            case EdgeFacet() as binding:
                rows, names = _edge_value_rows(f, shared)
            case SparseFacet() as binding:
                assert spec.default_slug is not None  # paired at import time
                rows, names = _sparse_value_rows(
                    f, shared, spec.key, binding, spec.default_slug
                )
            case _:
                continue
        counted[binding.name] = _tally_options(
            rows, _unanimous_cells(rows, shared), names, shared
        )
    return counted


def _title_facet(
    f: GameFilters, shared: _SharedFanout, exclude: TitleDimension, fk: str
) -> list[FacetOption]:
    rows, names = _title_dimension_value_rows(f, shared, exclude, fk)
    if _model_dimensions_active(f):
        carded = _unanimous_cells(rows, shared)
    else:
        carded, vacuous_names = _vacuous_title_cells(f, exclude, fk)
        names = {**names, **vacuous_names}
    return _tally_options(rows, carded, names, shared)


def _player_facet(f: GameFilters, shared: _SharedFanout) -> list[PlayerCountOption]:
    """Every bucket is returned, count 0 included — the bucket list is fixed
    UI, not a pruned value list."""
    rows = _player_value_rows(f, shared)
    names = {str(bucket): str(bucket) for bucket in PLAYER_BUCKETS}
    options = _tally_options(rows, _unanimous_cells(rows, shared), names, shared)
    by_bucket = {o.public_id: o.count for o in options}
    return [
        PlayerCountOption(bucket, by_bucket.get(str(bucket), 0))
        for bucket in PLAYER_BUCKETS
    ]


def _selected(value: str | None) -> tuple[str, ...]:
    return (value,) if value else ()


def _real_slugs(values: tuple[str, ...]) -> tuple[str, ...]:
    """A sparse selection's vocabulary slugs, ``UNCLASSIFIED`` dropped —
    ``with_selected`` must never put an ``unclassified`` option row in the
    payload (the canonical preset URL always carries the value)."""
    return tuple(v for v in values if v != UNCLASSIFIED)


def _with_selected_edges(
    options: list[FacetOption], selected: tuple[str, ...]
) -> list[FacetOption]:
    """The ``with_selected`` rule for edge keys, which have no catalog table
    to resolve names from: a selected value pruned to zero re-enters as its
    wire value at count 0 (an unknown key stays deselectable the same way)."""
    present = {o.public_id for o in options}
    extra = [FacetOption(v, v, 0) for v in selected if v not in present]
    if not extra:
        return options
    return sorted(options + extra, key=lambda o: o.name)


def game_facet_counts(f: GameFilters) -> GameFacetOptions:
    """Assemble every sidebar option list at card grain, each counted by the
    N-1 rule (its own dimension excluded), active selections re-included at
    count 0 via the shared :func:`with_selected` leaf.

    The counted lists come from the registry (:func:`_counted_facets`); this
    assembly stays explicit because it *is* the payload contract — each field
    pairs a counted list with its selected values and option model."""
    shared = _shared_fanout(f)
    counted = _counted_facets(f, shared)
    return GameFacetOptions(
        manufacturer=with_selected(
            counted["manufacturer"], _selected(f.manufacturer), Manufacturer
        ),
        person=with_selected(counted["person"], _selected(f.person), Person),
        tech_gen=with_selected(
            counted["tech_gen"], _selected(f.tech_gen), TechnologyGeneration
        ),
        display_type=with_selected(
            counted["display_type"], _selected(f.display_type), DisplayType
        ),
        system=with_selected(counted["system"], _selected(f.system), System),
        reward_type=with_selected(counted["reward_type"], f.reward_types, RewardType),
        edge=_with_selected_edges(counted["edge"], f.edge),
        cabinet=with_selected(counted["cabinet"], _real_slugs(f.cabinet), Cabinet),
        game_format=with_selected(
            counted["game_format"], _real_slugs(f.game_format), GameFormat
        ),
        production_status=with_selected(
            counted["production_status"],
            _real_slugs(f.production_status),
            ProductionStatus,
        ),
        theme=with_selected(counted["theme"], f.themes, Theme),
        feature=with_selected(counted["feature"], f.features, GameplayFeature),
        franchise=with_selected(
            _title_facet(f, shared, "franchise", "franchise"),
            _selected(f.franchise),
            Franchise,
        ),
        series=with_selected(
            _title_facet(f, shared, "series", "series"),
            _selected(f.series),
            Series,
        ),
        player_count=_player_facet(f, shared),
    )
