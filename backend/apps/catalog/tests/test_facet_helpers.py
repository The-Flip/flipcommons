"""Unit tests for the shared facet leaves in ``api/_facet_helpers.py``.

Titles' suite exercises these leaves through one shape only: a ``MachineModel``
root, ``title_id`` reverse key, slug-keyed values, a slug/DAG hierarchy. These
tests pin the **parameterization** that makes the leaves genuinely domain-free —
the shapes the second consumer (manufacturers) will use but that titles never
hits: a non-``MachineModel`` root, a path-keyed self-referential hierarchy, a
non-slug ``public_id_field``, and the roll-up's distinct-id (not summed) counting.
Until manufacturers exists they are the only guard on that generality.
"""

from __future__ import annotations

import pytest
from django.db.models import Q

from apps.catalog.api._facet_helpers import (
    FacetOption,
    ancestor_map,
    bounds,
    count_distinct,
    hierarchy_rollup,
    with_selected,
)
from apps.catalog.models import Franchise, Location, MachineModel, Manufacturer, Title
from apps.core.models import EntityStatus

from .conftest import make_machine_model

# Active-non-variant guard at the bare MachineModel root, as titles' assembly
# passes it to the count/bounds leaves.
_MODEL_GUARD = Q(variant_of__isnull=True) & (
    Q(status=EntityStatus.ACTIVE) | Q(status__isnull=True)
)


# ---------------------------------------------------------------------------
# hierarchy_rollup — distinct-id union, NOT summed leaf counts (pure)
# ---------------------------------------------------------------------------


def test_hierarchy_rollup_counts_distinct_ids_not_summed() -> None:
    """An entity tagged in two sibling descendants counts **once** for the shared
    parent — the trap a sum-of-leaf-counts rollup would double-count."""
    ancestors = {
        "usa/il/chicago": {"usa/il/chicago", "usa/il", "usa"},
        "usa/il/peoria": {"usa/il/peoria", "usa/il", "usa"},
    }
    names = {
        "usa": "USA",
        "usa/il": "Illinois",
        "usa/il/chicago": "Chicago",
        "usa/il/peoria": "Peoria",
    }
    # Entity 1 sits in BOTH Chicago and Peoria (two siblings under Illinois).
    pairs = [(1, "usa/il/chicago"), (1, "usa/il/peoria")]
    counts = {o.public_id: o.count for o in hierarchy_rollup(pairs, ancestors, names)}
    assert counts["usa/il"] == 1  # NOT 2 — the double-count guard
    assert counts["usa"] == 1
    assert counts["usa/il/chicago"] == 1
    assert counts["usa/il/peoria"] == 1


def test_hierarchy_rollup_resolves_names_and_sorts() -> None:
    ancestors = {"a": {"a"}, "b": {"b"}}
    names = {"a": "Zeta", "b": "Alpha"}
    options = hierarchy_rollup([(1, "a"), (2, "b")], ancestors, names)
    assert [o.name for o in options] == ["Alpha", "Zeta"]  # sorted by name


# ---------------------------------------------------------------------------
# ancestor_map — path-keyed self-referential tree (manufacturers' shape)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ancestor_map_over_location_path_tree() -> None:
    """``ancestor_map`` parameterized on ``(location_path, parent__location_path)``
    — a single-FK tree keyed on a path, not a slug DAG. The chain Chicago → Illinois
    → USA must resolve explicitly."""
    usa = Location.objects.create(location_path="usa", slug="usa", name="USA")
    il = Location.objects.create(
        location_path="usa/il", slug="il", name="Illinois", parent=usa
    )
    Location.objects.create(
        location_path="usa/il/chicago", slug="chicago", name="Chicago", parent=il
    )

    amap = ancestor_map(Location, "location_path", "parent__location_path")
    assert amap["usa/il/chicago"] == {"usa/il/chicago", "usa/il", "usa"}
    assert amap["usa/il"] == {"usa/il", "usa"}
    assert amap["usa"] == {"usa"}


# ---------------------------------------------------------------------------
# count_distinct — non-MachineModel root, guard, null-group drop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_count_distinct_titles_rooted_drops_null_group() -> None:
    """Rooted at ``Title`` (reverse_key ``pk``, no guard) — the shape titles' own
    franchise/series facet uses, distinct from the ``MachineModel`` root. The
    null-franchise title produces no option."""
    fr = Franchise.objects.create(slug="fr-1", name="Franchise One")
    Title.objects.create(name="A", slug="a", franchise=fr)
    Title.objects.create(name="B", slug="b", franchise=fr)
    Title.objects.create(name="C", slug="c")  # no franchise → dropped

    options = count_distinct(
        Title,
        Title.objects.all(),
        reverse_key="pk",
        relation="franchise",
        guard=Q(),
    )
    assert options == [FacetOption("fr-1", "Franchise One", 2)]


@pytest.mark.django_db
def test_count_distinct_guard_excludes_rows() -> None:
    """The *guard* arg scopes the count root — a guarded-out row doesn't tally."""
    fr = Franchise.objects.create(slug="fr-1", name="Franchise One")
    Title.objects.create(name="A", slug="a", franchise=fr)
    Title.objects.create(name="B", slug="b", franchise=fr)

    options = count_distinct(
        Title,
        Title.objects.all(),
        reverse_key="pk",
        relation="franchise",
        guard=Q(slug="a"),  # only title A passes the guard
    )
    assert options == [FacetOption("fr-1", "Franchise One", 1)]


# ---------------------------------------------------------------------------
# bounds — explicit guard drops inactive rows from min/max
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bounds_guard_excludes_inactive_rows() -> None:
    make_machine_model(name="m1", year=1980)
    make_machine_model(name="m2", year=2000)
    make_machine_model(name="m3", year=1970, status=EntityStatus.DELETED)

    result = bounds(
        MachineModel,
        Title.objects.all(),
        reverse_key="title_id",
        lookup="year",
        guard=_MODEL_GUARD,
        cast=int,
    )
    assert result.min == 1980  # the deleted 1970 model is guarded out
    assert result.max == 2000
    assert isinstance(result.min, int)  # cast applied, never 1980.0


# ---------------------------------------------------------------------------
# with_selected — non-slug public_id_field re-includes a pruned selection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_with_selected_keyed_on_location_path() -> None:
    """A selection pruned to count 0 is restored with its real name, keyed by a
    ``location_path`` rather than a slug (location's identity field)."""
    Location.objects.create(location_path="usa/il", slug="il", name="Illinois")
    restored = with_selected([], ("usa/il",), Location, public_id_field="location_path")
    assert restored == [FacetOption("usa/il", "Illinois", 0)]


@pytest.mark.django_db
def test_with_selected_slug_default_does_not_duplicate_present_value() -> None:
    Manufacturer.objects.create(slug="williams", name="Williams")
    present = [FacetOption("williams", "Williams", 3)]
    # A present selection keeps its real count and isn't re-added.
    assert with_selected(present, ("williams",), Manufacturer) == present
