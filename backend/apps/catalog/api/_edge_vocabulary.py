"""The relationship-filter key vocabulary — ``edge=<key>`` / ``edge=<key>:in``.

The catalog stores Model-to-Model relationships three ways — the lineage
self-FKs on ``MachineModel`` (``variant_of``, ``remake_of``,
``export_edition_of``), typed ``ModelRelationship`` edge rows and the
licensing axis on those rows — and the split is invisible at the read layer.
One closed key vocabulary covers all three, with **direction** as an
orthogonal axis: ``bootleg`` selects Models carrying an unlicensed-copy
out-edge, ``bootleg:in`` the Models such an edge points at.

Nearly everything is introspected rather than described a second time: the
lineage keys walk ``MachineModel._meta`` for the self-FKs, the type keys
iterate ``RelationshipType``. Two declarations remain:
``MachineModel.self_fk_roles``, which says which self-FKs are lineage, and the
composites — no introspection yields the word "bootleg" for
``(copy, unlicensed)``.

Liveness is asymmetric by design. An **outbound** predicate tests only that
the edge or FK exists — the fact is recorded about the subject Model, and
some edges name a free-text donor with no catalog record at all, which must
still count. An **inbound** predicate requires the far-end Model *and its
Title* to be live: "has been bootlegged" must not card a record whose only
bootleg is soft-deleted and invisible everywhere else on the site.

An unknown or malformed ``edge`` value matches nothing (the nonexistent-tag
feel), never a validation error: :func:`parse_edge_value` returns ``None``
and the caller empties the queryset.

Overlapping facts are deliberately not reconciled: a Model can carry both a
lineage FK and a typed edge to the same target, and a predicate is an
existence test per key — a Model satisfying two keys matches both.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, NamedTuple, assert_never, get_args

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Exists, OuterRef, Q

from apps.core.models import active_status_q

from ..models import (
    LicenseStatus,
    MachineModel,
    ModelRelationship,
    RelationshipType,
    SelfFkRole,
)

EdgeDirection = Literal["out", "in"]

# The runtime direction tuple, derived from the Literal so the two can't
# diverge (the MODEL_DIMENSIONS pattern).
EDGE_DIRECTIONS: Final[tuple[EdgeDirection, ...]] = get_args(EdgeDirection)

_IN_SUFFIX: Final = ":in"


class LineageEdge(NamedTuple):
    """A lineage key: the relationship is a scalar self-FK on the subject
    Model, with no licensing axis. *field* is the FK's field name, which is
    also the key."""

    field: str


class TypedEdge(NamedTuple):
    """A ``ModelRelationship`` key: a relationship type, optionally narrowed
    to one licensing cell (the composites)."""

    relationship_type: RelationshipType
    license_status: LicenseStatus | None = None


EdgeSpec = LineageEdge | TypedEdge

# The named (type, licensing) cells — declared, not derived, because no
# introspection yields the domain words. Defined by the predicate they mean
# (bootleg *is* the unlicensed cell, not "not licensed"): an unknown-status
# copy matches ``copy`` and neither composite, which is a correct answer
# about what the catalog currently knows.
_COMPOSITES: Final[dict[str, TypedEdge]] = {
    "bootleg": TypedEdge(RelationshipType.COPY, LicenseStatus.UNLICENSED),
    "licensed_build": TypedEdge(RelationshipType.COPY, LicenseStatus.LICENSED),
}


def _lineage_field_names() -> tuple[str, ...]:
    """The filterable lineage self-FK names, in model declaration order.

    Which fields *are* self-FKs comes from ``_meta`` (concrete fields only);
    which of those are lineage comes from the :class:`SelfFkRole` verdicts in
    ``MachineModel.self_fk_roles``. A self-FK with no verdict fails here.
    """
    self_fks = tuple(
        f.name
        for f in MachineModel._meta.fields
        if f.is_relation and f.related_model is MachineModel
    )
    roles = MachineModel.self_fk_roles
    if set(self_fks) != set(roles):
        undeclared = sorted(set(self_fks) - set(roles))
        stale = sorted(set(roles) - set(self_fks))
        raise ImproperlyConfigured(
            "MachineModel.self_fk_roles does not match the model's self-FKs — "
            f"undeclared: {undeclared or 'none'}; stale: {stale or 'none'}. "
            "Classify every self-FK as SelfFkRole.LINEAGE (it becomes a public "
            "`edge=` filter key and a facet entry) or SelfFkRole.ADMINISTRATIVE."
        )
    return tuple(n for n in self_fks if roles[n] is SelfFkRole.LINEAGE)


def _build_registry() -> dict[str, EdgeSpec]:
    registry: dict[str, EdgeSpec] = {}
    for name in _lineage_field_names():
        registry[name] = LineageEdge(name)
    for rel_type in RelationshipType:
        registry[rel_type.value] = TypedEdge(rel_type)
    registry.update(_COMPOSITES)
    return registry


# The closed key registry, in declaration order: lineage, types, composites.
EDGE_KEYS: Final[Mapping[str, EdgeSpec]] = _build_registry()

# The three sources may not collide — a RelationshipType value shadowing a
# lineage field name (or a composite shadowing either) would silently drop a
# key from the vocabulary.
assert len(EDGE_KEYS) == (
    len(_lineage_field_names()) + len(RelationshipType) + len(_COMPOSITES)
)


class EdgeSelection(NamedTuple):
    """One parsed ``edge`` param value: a registry key plus a direction."""

    key: str
    direction: EdgeDirection


def parse_edge_value(value: str) -> EdgeSelection | None:
    """``"bootleg"`` → outbound, ``"bootleg:in"`` → inbound, anything else
    (unknown key, stray suffix, wrong case) → ``None``."""
    if value.endswith(_IN_SUFFIX):
        key = value[: -len(_IN_SUFFIX)]
        direction: EdgeDirection = "in"
    else:
        key = value
        direction = "out"
    if key not in EDGE_KEYS:
        return None
    return EdgeSelection(key, direction)


def edge_wire_value(selection: EdgeSelection) -> str:
    """The URL/API spelling of *selection* — :func:`parse_edge_value`'s
    inverse."""
    if selection.direction == "out":
        return selection.key
    return f"{selection.key}{_IN_SUFFIX}"


def edge_q(selection: EdgeSelection) -> Q:
    """The membership predicate for *selection*, correlated on the subject
    ``MachineModel`` pk — composable with any queryset rooted there.

    Outbound tests bare existence; inbound gates the far end (Model and its
    Title) on liveness — see the module docstring for why the asymmetry is
    deliberate.
    """
    spec = EDGE_KEYS[selection.key]
    match spec:
        case LineageEdge(field=field):
            if selection.direction == "out":
                return Q(**{f"{field}__isnull": False})
            return Q(
                Exists(
                    MachineModel.objects.active()
                    .filter(active_status_q("title"))
                    .filter(**{field: OuterRef("pk")})
                )
            )
        case TypedEdge(relationship_type=rel_type, license_status=license_status):
            edges = ModelRelationship.objects.filter(relationship_type=rel_type)
            if license_status is not None:
                edges = edges.filter(license_status=license_status)
            if selection.direction == "out":
                return Q(Exists(edges.filter(machine_model=OuterRef("pk"))))
            return Q(
                Exists(
                    edges.filter(target_machine=OuterRef("pk"))
                    .filter(active_status_q("machine_model"))
                    .filter(active_status_q("machine_model__title"))
                )
            )
        case _:
            assert_never(spec)
