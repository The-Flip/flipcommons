"""Domain-free leaf helpers shared by the catalog listing pages' faceted search.

These are the genuinely reusable *leaves* — the count/search/hierarchy SQL whose
subtlety was tuned once on titles and must not be re-derived per entity. They name
**no domain noun**: every model, relation and guard is a call argument, so an
SQL/perf fix here lands on every page at once.

What stays per-entity (and is **not** here): the N-1 exclude loop, the per-dimension
predicates, and the ``facet_counts`` assembly that wires these leaves together. See
``_title_facets.py`` for titles' assembly; manufacturers gets its own.

Deliberately **not** extracted yet: the composite diacritic-fold *match* (the
``q``-branch Q-assembly). Only the primitives :class:`_Unaccent` and :func:`_fold`
live here; the match itself requires an annotation step and its real shape is driven
by manufacturers' multi-branch OR, which doesn't exist until that page is built.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import Count, F, Func, Max, Min, Model, Q, QuerySet, TextField

# ---------------------------------------------------------------------------
# Shared option / bounds value types
# ---------------------------------------------------------------------------


# dataclass, not NamedTuple: a NamedTuple field named ``count`` would shadow
# tuple.count and mypy rejects it.
@dataclass(frozen=True)
class FacetOption:
    """One selectable value of a facet, with its live N-1 count.

    ``public_id`` is the underlying entity's URL identity — a ``slug`` for most
    facets, a ``location_path`` for location."""

    public_id: str
    name: str
    count: int


class Bounds[N: (int, float)](NamedTuple):
    """Inclusive min/max for a range facet. ``None`` when the filtered set has no
    values for the dimension. Parameterized so year bounds stay ``int`` (the field
    is integral — never serialize ``1980.0``) and rating bounds are ``float``."""

    min: N | None
    max: N | None


# ---------------------------------------------------------------------------
# Diacritic-fold primitives (the composite match stays per-entity — see module doc)
# ---------------------------------------------------------------------------


class _Unaccent(Func):
    """Postgres ``unaccent(text)`` — strips diacritics (é → e). Emitted ONLY on the
    Postgres branch of a ``q`` filter; never reaches SQLite."""

    function = "UNACCENT"
    output_field = TextField()


def _fold(text: str) -> str:
    """Diacritic-fold + lowercase a query term to match ``LOWER(UNACCENT(field))`` on
    Postgres. NFD + strip combining marks ≈ ``unaccent`` for Latin scripts."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.lower()


# ---------------------------------------------------------------------------
# Model-rooted distinct count (the N-1 count leaf)
# ---------------------------------------------------------------------------


def count_distinct(
    root: type[Model],
    ids: QuerySet[Model],
    *,
    reverse_key: str,
    relation: str,
    guard: Q,
    public_id_field: str = "slug",
) -> list[FacetOption]:
    """Distinct count of entities per value of a model-level facet.

    Counts root at the **model**, not the entity: group ``root``'s rows by the facet
    value and count distinct entities reached through *reverse_key*. Rooting where the
    *guard* and the GROUP BY share one row is what stops Django building a separate join
    for the guard — the trap that leaks variant/retired values into counts.

    - *root* — the model the rows live on (e.g. ``MachineModel``).
    - *ids* — the N-1 base entity queryset, used only as a bare ``reverse_key__in``
      subquery (Django selects just the pk — no correlated subquery, no stray GROUP
      BY).
    - *reverse_key* — how a row returns to the counted entity (titles ``title_id``,
      manufacturers ``corporate_entity__manufacturer_id``).
    - *relation* — the **count-root-relative** path to the value holder (``system``,
      ``credits__person``); the helper derives ``{relation}__{public_id_field}``
      and ``{relation}__name`` from it.
    - *public_id_field* — the related model's URL-identity field (its
      ``public_id_field`` ClassVar): ``slug`` for most, ``location_path`` for location.
    - *guard* — applied at the count root (e.g. active non-variant). Without it,
      inactive rows leak counts.

    Drops the null group (``.exclude(public_id=None)``) — nullable facets like
    ``technology_generation`` would otherwise emit a null option that fails schema
    validation. Aliased to ``opt_public_id``/``opt_name`` so a bare ``slug``/``name``
    can't collide with the root model's own fields.
    """
    # ``_default_manager``, not ``.objects``: the generically-typed manager on a
    # ``type[Model]`` argument (``.objects`` isn't on django-stubs' ``type[Model]``).
    rows = (
        root._default_manager.filter(guard, **{f"{reverse_key}__in": ids})
        .values(
            opt_public_id=F(f"{relation}__{public_id_field}"),
            opt_name=F(f"{relation}__name"),
        )
        .exclude(opt_public_id=None)  # values()-created alias
        .annotate(count=Count(reverse_key, distinct=True))
        .order_by("opt_name")
    )
    return [FacetOption(r["opt_public_id"], r["opt_name"], r["count"]) for r in rows]


# ---------------------------------------------------------------------------
# Model-rooted min/max (the range-facet leaf)
# ---------------------------------------------------------------------------


def bounds[N: (int, float)](
    root: type[Model],
    ids: QuerySet[Model],
    *,
    reverse_key: str,
    lookup: str,
    guard: Q,
    cast: Callable[[float], N],
) -> Bounds[N]:
    """Min/max of a model-level numeric field over the guarded rows of the filtered
    set, coerced via *cast* (``int`` for year, ``float`` for rating).

    Model-rooted (``root.objects.filter(reverse_key__in=ids, guard)``), **not**
    ``bounds(qs, path)`` over the entity queryset — the latter re-introduces the
    guard/group separate-join leak ``count_distinct`` avoids."""
    agg = root._default_manager.filter(guard, **{f"{reverse_key}__in": ids}).aggregate(
        lo=Min(lookup), hi=Max(lookup)
    )
    lo, hi = agg["lo"], agg["hi"]
    return Bounds(
        cast(lo) if lo is not None else None,
        cast(hi) if hi is not None else None,
    )


# ---------------------------------------------------------------------------
# Hierarchy roll-up (parent counts include child-tagged entities)
# ---------------------------------------------------------------------------


def ancestor_map(
    model_cls: type[Model], public_id_field: str, parent_lookup: str
) -> dict[str, set[str]]:
    """Map each public_id → the set of all its ancestor public_ids (including itself),
    from **one** ``values_list(public_id_field, parent_lookup)`` scan.

    Parameterized over the public_id/parent fields so both hierarchy shapes reduce to
    the same scan: a ManyToMany DAG keyed on slug (themes/features —
    ``("slug", "parents__slug")``) and a self-referential tree keyed on path
    (locations — ``("location_path", "parent__location_path")``). A single-parent
    tree is just ≤1 row per node. Cycle-guarded (a DAG may revisit)."""
    parents: dict[str, set[str]] = {}
    for public_id, parent in model_cls._default_manager.values_list(
        public_id_field, parent_lookup
    ):
        parents.setdefault(public_id, set())
        if parent is not None:
            parents[public_id].add(parent)

    cache: dict[str, set[str]] = {}

    def resolve(public_id: str, visiting: frozenset[str]) -> set[str]:
        if public_id in cache:
            return cache[public_id]
        result = {public_id}
        if public_id in visiting:
            return result
        nxt = visiting | {public_id}
        for parent in parents.get(public_id, ()):
            result |= resolve(parent, nxt)
        cache[public_id] = result
        return result

    return {public_id: resolve(public_id, frozenset()) for public_id in parents}


def hierarchy_rollup(
    pairs: Iterable[tuple[int, str]],
    ancestors: dict[str, set[str]],
    names: dict[str, str],
) -> list[FacetOption]:
    """Roll raw ``(entity_id, leaf_public_id)`` pairs up to ancestor counts.

    For each pair, expand the leaf public_id to its ancestors (via *ancestors*) and
    union a **set** of distinct entity ids per ancestor; the count is ``len(set)``.
    Unioning distinct ids — never summing leaf counts — is essential: an entity tagged
    in two sibling descendants would otherwise double-count their shared parent. Sorted
    by display name (resolved from *names*)."""
    entity_ids_by_public_id: dict[str, set[int]] = {}
    for entity_id, leaf_public_id in pairs:
        for public_id in ancestors.get(leaf_public_id, {leaf_public_id}):
            entity_ids_by_public_id.setdefault(public_id, set()).add(entity_id)
    options = [
        FacetOption(public_id, names.get(public_id, public_id), len(entity_ids))
        for public_id, entity_ids in entity_ids_by_public_id.items()
    ]
    options.sort(key=lambda o: o.name)
    return options


# ---------------------------------------------------------------------------
# Re-include an active selection the N-1 count pruned to zero
# ---------------------------------------------------------------------------


def with_selected(
    options: list[FacetOption],
    selected: tuple[str, ...],
    model_cls: type[Model],
    *,
    public_id_field: str = "slug",
) -> list[FacetOption]:
    """Keep active selections visible even when the N-1 count prunes them to zero.

    The GROUP BY drops any value with no matching entities (the value-pruning) — but a
    value the user has *selected* can prune to zero whenever the combined filters yield
    an empty result set. Dropping it then strands the selection: the sidebar can't show
    it deselectable and the active-filter chip can't resolve its name, falling back to
    the raw public_id. So re-add each missing selection at count 0, name resolved from
    the unpruned catalog table (keyed by *public_id_field* — ``slug`` for most facets, a
    ``location_path`` for location), re-sorted by name to match the count query's
    ``order_by('opt_name')``. Unselected pruned values stay dropped."""
    if not selected:
        return options
    present = {o.public_id for o in options}
    missing = [public_id for public_id in selected if public_id not in present]
    if not missing:
        return options
    names = dict(
        model_cls._default_manager.filter(
            **{f"{public_id_field}__in": missing}
        ).values_list(public_id_field, "name")
    )
    restored = [
        FacetOption(public_id, names.get(public_id, public_id), 0)
        for public_id in missing
    ]
    return sorted([*options, *restored], key=lambda o: o.name)
