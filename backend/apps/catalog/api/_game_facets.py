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
from ._game_rows import (
    PLAYER_BUCKETS,
    GameFilters,
    ModelDimension,
    TaxonomyExpansion,
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
    slug_path: str,
    name_path: str,
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
        .filter(**{f"{slug_path}__isnull": False})
        .values_list("pk", "title_id", "variant_of_id", slug_path, name_path)
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
    taxonomy: type[Theme] | type[GameplayFeature],
    path: str,
) -> tuple[list[_FacetValueRow], dict[str, str]]:
    """Value rows for a taxonomy dimension: each Model's direct tags exploded
    to every ancestor value, de-duplicated per ``(pk, value)`` — the DAG can
    reach one ancestor twice. Base per :func:`facet_exclude`, as in
    :func:`_value_rows`; themes and features accumulate, so theirs stays
    applied."""
    ancestors = ancestor_map(taxonomy, "slug", "parents__slug")
    names: dict[str, str] = dict(taxonomy._default_manager.values_list("slug", "name"))
    gate = _title_only_q(f, prefix="title__")
    raw = (
        model_only_models(
            f, exclude=facet_exclude(dimension), expansion=shared.expansion
        )
        .filter(gate)
        # filter, not exclude — see _value_rows on multivalued isnull.
        .filter(**{f"{path}__slug__isnull": False})
        .values_list("pk", "title_id", "variant_of_id", f"{path}__slug")
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


def _model_facet(
    f: GameFilters,
    shared: _SharedFanout,
    dimension: ModelDimension,
    slug_path: str,
    name_path: str,
) -> list[FacetOption]:
    rows, names = _value_rows(f, shared, dimension, slug_path, name_path)
    return _tally_options(rows, _unanimous_cells(rows, shared), names, shared)


def _hierarchical_facet(
    f: GameFilters,
    shared: _SharedFanout,
    dimension: ModelDimension,
    taxonomy: type[Theme] | type[GameplayFeature],
    path: str,
) -> list[FacetOption]:
    rows, names = _hierarchical_value_rows(f, shared, dimension, taxonomy, path)
    return _tally_options(rows, _unanimous_cells(rows, shared), names, shared)


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


def game_facet_counts(f: GameFilters) -> GameFacetOptions:
    """Assemble every sidebar option list at card grain, each counted by the
    N-1 rule (its own dimension excluded), active selections re-included at
    count 0 via the shared :func:`with_selected` leaf."""
    shared = _shared_fanout(f)
    return GameFacetOptions(
        manufacturer=with_selected(
            _model_facet(
                f,
                shared,
                "manufacturer",
                "corporate_entity__manufacturer__slug",
                "corporate_entity__manufacturer__name",
            ),
            _selected(f.manufacturer),
            Manufacturer,
        ),
        person=with_selected(
            _model_facet(
                f, shared, "person", "credits__person__slug", "credits__person__name"
            ),
            _selected(f.person),
            Person,
        ),
        tech_gen=with_selected(
            _model_facet(
                f,
                shared,
                "tech_gen",
                "technology_generation__slug",
                "technology_generation__name",
            ),
            _selected(f.tech_gen),
            TechnologyGeneration,
        ),
        display_type=with_selected(
            _model_facet(
                f, shared, "display_type", "display_type__slug", "display_type__name"
            ),
            _selected(f.display_type),
            DisplayType,
        ),
        system=with_selected(
            _model_facet(f, shared, "system", "system__slug", "system__name"),
            _selected(f.system),
            System,
        ),
        reward_type=with_selected(
            _model_facet(
                f, shared, "reward_types", "reward_types__slug", "reward_types__name"
            ),
            f.reward_types,
            RewardType,
        ),
        theme=with_selected(
            _hierarchical_facet(f, shared, "themes", Theme, "themes"),
            f.themes,
            Theme,
        ),
        feature=with_selected(
            _hierarchical_facet(
                f, shared, "features", GameplayFeature, "gameplay_features"
            ),
            f.features,
            GameplayFeature,
        ),
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
