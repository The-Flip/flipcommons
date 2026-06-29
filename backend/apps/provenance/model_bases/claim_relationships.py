"""The relationship declaration vocabulary — pure-data specs and their read surface.

A :class:`ClaimRelationshipSpec` is a ClassVar on each :class:`ClaimThroughModel`
subclass: a pure-data declaration of one claim-controlled relationship namespace
(its subject, member columns, payload columns and conflict/scope policy). It
carries no model-class reference — FK targets are introspected from ``_meta`` at
build time — and no resolver callable, so resolution behavior lives elsewhere
and the spec stays a domain-neutral, lift-out-ready declaration.

The specs are consumed generically: the validation-schema derivation and the
resolution-projection builder both read them, and :func:`relationships_for` is
the one public query that pairs each spec with the runtime facts a bare spec
can't carry (its owning through-model, the concrete subject model and the live
reverse/M2M accessor name).

Kept a core-only leaf alongside :mod:`.models`: imports only ``apps.core`` and
the Django app registry, never the provenance domain or any catalog model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import assert_never

from django.apps import apps
from django.db.models import ForeignKey

from apps.core.types import (
    ClaimFieldName,
    ClaimValueKey,
    ColumnName,
    IdentityPartName,
)

from .models import ClaimControlledModel, ClaimThroughModel


class ScopePolicy(Enum):
    """Whether a namespace honors the changed-subject scope or resolves whole-type.

    ``SUBJECTS`` re-materializes only the passed subjects (the common, efficient
    case). ``FULL_TYPE`` (aliases, parent hierarchies) ignores the scope and
    re-resolves the entire type. ``FULL_TYPE`` projections *could* be scoped —
    their reads filter by subject — so subject-scoping them is a valid,
    idempotent optimization, not a correctness requirement.
    """

    SUBJECTS = auto()
    FULL_TYPE = auto()


class EmptyTargetPolicy(Enum):
    """What an empty FK-target set means for a member during resolution.

    ``DROP_INVALID`` (the default — today's behavior for every namespace):
    members with invalid FKs are dropped, so an empty target table drops all
    members and the existing rows are deleted. ``SKIP_NAMESPACE`` (only
    ``Credit.role``): the projection is skipped entirely so an unseeded
    vocabulary can't wipe existing rows.
    """

    DROP_INVALID = auto()
    SKIP_NAMESPACE = auto()


@dataclass(frozen=True, slots=True)
class SingleSubject:
    """A namespace whose claim subject is one FK on the through-model."""

    fk_name: ColumnName  # "machinemodel", "title"


@dataclass(frozen=True, slots=True)
class XorSubject:
    """A namespace whose subject is one of two mutually-exclusive FKs.

    Order is not semantic — each branch's subject model is introspected from
    ``_meta``. Credit's model/series XOR is the only case.
    """

    left_fk: ColumnName  # "model"
    right_fk: ColumnName  # "series"


type SubjectSpec = SingleSubject | XorSubject
# Self-referential parent hierarchies (Theme/GameplayFeature ``parents``) ride
# SingleSubject: the child FK is the subject and the parent FK is the identity
# member, so the two-FK self-parent through-model needs no dedicated variant.


@dataclass(frozen=True, slots=True)
class MemberField:
    """One member column of a through-row — the FK or literal that forms identity.

    ``field`` is the through-model column ("theme", "person", "value").
    ``value_key`` is the JSON value-dict key when it differs from ``field``.
    ``identity`` is the ``claim_key`` identity label. ``lookup_field`` is the FK
    target lookup field (the target *model* is introspected, never named).
    ``empty_target`` decides what an empty target-PK set means (see
    :class:`EmptyTargetPolicy`).
    """

    field: ColumnName
    value_key: ClaimValueKey | None = None
    identity: IdentityPartName | None = None
    lookup_field: ColumnName = "pk"
    empty_target: EmptyTargetPolicy = EmptyTargetPolicy.DROP_INVALID


@dataclass(frozen=True, slots=True)
class PayloadField:
    """A non-identity payload column of a through-row (e.g. gameplay ``count``)."""

    field: ColumnName
    value_key: ClaimValueKey | None = None
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class ClaimRelationshipSpec:
    """Pure-data declaration of one claim-controlled relationship namespace.

    Declared as a ClassVar on each :class:`ClaimThroughModel` subclass and
    consumed generically to derive both the validation schema and the resolution
    projection. ``members`` cardinality is 1 (plain/literal) or 2 (credit),
    enforced by the model's startup validator.
    """

    namespace: ClaimFieldName
    subject: SubjectSpec
    members: tuple[MemberField, ...]
    payload: tuple[PayloadField, ...] = ()
    ignore_conflicts: bool = False
    scope: ScopePolicy = ScopePolicy.SUBJECTS


type MemberAccessor = str
"""The attribute on a subject model that reaches a relationship's members — an
M2M field name ("themes") or a reverse-FK accessor ("credits")."""


@dataclass(frozen=True, slots=True)
class ClaimRelationshipBinding:
    """A spec paired with the runtime facts a bare spec can't carry.

    The spec is pure data with no model-class reference, so its owning
    through-model, the concrete subject model, the subject FK column on the
    through-model and the live reverse/M2M accessor name come from the binding
    rather than a re-walk or object-identity lookup. ``subject_fk`` is the
    branch-resolved FK name — for an :class:`XorSubject` it identifies *which*
    branch this binding's subject occupies, so a consumer (e.g. the resolution
    projection builder) derives ``{subject_fk}_id`` without re-introspecting.
    """

    spec: ClaimRelationshipSpec
    through_model: type[ClaimThroughModel]
    subject_model: type[ClaimControlledModel]
    subject_fk: ColumnName
    accessor: MemberAccessor


type BindingsBySubject = dict[
    type[ClaimControlledModel], tuple[ClaimRelationshipBinding, ...]
]
"""Each claim-controlled subject model mapped to its relationship bindings."""


_bindings_by_subject: BindingsBySubject | None = None


def _ensure_bindings() -> BindingsBySubject:
    """Build and cache the subject → bindings index on first access."""
    global _bindings_by_subject
    if _bindings_by_subject is None:
        _bindings_by_subject = _build_bindings()
    return _bindings_by_subject


def relationships_for(
    model: type[ClaimControlledModel],
) -> tuple[ClaimRelationshipBinding, ...]:
    """Every claim-relationship binding whose subject is ``model``.

    The one public query over the spec registry. Walks the concrete
    :class:`ClaimThroughModel` models, expands each spec into one binding per
    subject (an :class:`XorSubject` yields two), and returns those whose subject
    is ``model``.

    Coverage boundary: explicit ClassVar through-model specs only (incl. the
    self-referential parent hierarchies) — not aliases (bespoke) or media
    (content-type keyed). Returns an empty tuple for any model with no declared
    spec.
    """
    return _ensure_bindings().get(model, ())


def all_relationship_bindings() -> tuple[ClaimRelationshipBinding, ...]:
    """Every claim-relationship binding, across all subjects.

    The flattened form of the per-subject index :func:`relationships_for`
    queries. The schema and resolution-projection derivations iterate the whole
    binding set (grouping by namespace, or building one projection per
    ``(namespace, subject)``), so they read this rather than re-walking
    :class:`ClaimThroughModel` and re-deriving subject/accessor. Same coverage
    boundary as :func:`relationships_for`: explicit ClassVar through-model specs
    only (incl. parent hierarchies) — not aliases or media.
    """
    return tuple(
        binding for bindings in _ensure_bindings().values() for binding in bindings
    )


def _build_bindings() -> BindingsBySubject:
    """Build the subject → bindings map once, after the app registry is ready.

    Enumerates via the app registry (not ``__subclasses__()``, which sees only
    direct subclasses) so a through-model nested under an intermediate abstract
    base is still found. Guarded by ``check_apps_ready()`` so an early call can't
    snapshot an incomplete model set.
    """
    apps.check_apps_ready()
    by_subject: dict[type[ClaimControlledModel], list[ClaimRelationshipBinding]] = {}
    for model in apps.get_models():
        if not issubclass(model, ClaimThroughModel) or model._meta.abstract:
            continue
        spec = model.claim_relationship_spec
        for binding in _bindings_for_through(model, spec):
            by_subject.setdefault(binding.subject_model, []).append(binding)
    return {subject: tuple(bindings) for subject, bindings in by_subject.items()}


def _bindings_for_through(
    through_model: type[ClaimThroughModel], spec: ClaimRelationshipSpec
) -> list[ClaimRelationshipBinding]:
    """Every binding a through-model's spec yields — one per subject FK.

    A :class:`SingleSubject` yields one binding; an :class:`XorSubject` yields two.
    """
    fk_names: tuple[ColumnName, ...]
    # Exhaustive dispatch over the closed SubjectSpec union — the sanctioned
    # alternative to isinstance-on-model branching. assert_never makes mypy flag
    # the missing case the moment a new variant is added to the union, instead of
    # silently leaving fk_names unbound.
    match spec.subject:
        case SingleSubject(fk_name):
            fk_names = (fk_name,)
        case XorSubject(left_fk, right_fk):
            fk_names = (left_fk, right_fk)
        case _:
            assert_never(spec.subject)
    return [_binding_for_subject(through_model, spec, fk_name) for fk_name in fk_names]


def _binding_for_subject(
    through_model: type[ClaimThroughModel],
    spec: ClaimRelationshipSpec,
    fk_name: ColumnName,
) -> ClaimRelationshipBinding:
    """The binding for one subject FK — its subject model and member-accessor.

    The subject model is the FK's target. The accessor is the attribute on the
    subject model that reaches the members, which differs by relation shape:

    - **M2M** — the members are reached via a ``ManyToManyField`` on the subject
      whose ``through`` is this through-model (e.g. ``MachineModel.themes``); the
      accessor is that field's name. True even when the M2M uses an explicit
      ``through=`` model (themes/tags/reward_types/gameplay_features).
    - **Reverse FK** — the through-model rows *are* the members, reached via the
      reverse accessor of the subject FK (e.g. ``Credit.model`` →
      ``MachineModel.credits``); the accessor is that reverse name.
    """
    subject_fk = through_model._meta.get_field(fk_name)
    assert isinstance(subject_fk, ForeignKey), (
        f"{through_model.__name__}.{fk_name} must be a ForeignKey subject"
    )
    subject_model = subject_fk.related_model
    # related_model is ``type[Model] | "self"``; Django resolves "self" to the
    # concrete class once apps are loaded, so by here it is always a class.
    assert not isinstance(subject_model, str)
    assert issubclass(subject_model, ClaimControlledModel), (
        f"subject {subject_model.__name__} of {through_model.__name__} "
        f"is not claim-controlled"
    )

    accessor: MemberAccessor | None = None
    for m2m in subject_model._meta.many_to_many:
        if m2m.remote_field.through is through_model:
            accessor = m2m.name
            break
    else:
        accessor = subject_fk.remote_field.get_accessor_name()
    assert accessor is not None, (
        f"{through_model.__name__}.{fk_name} suppresses its reverse accessor "
        f"(related_name='+'); cannot reach members"
    )
    return ClaimRelationshipBinding(
        spec=spec,
        through_model=through_model,
        subject_model=subject_model,
        subject_fk=fk_name,
        accessor=accessor,
    )
