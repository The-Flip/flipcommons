"""System check for the ``ClaimThroughModel`` relationship-spec contract.

Validates the *class shape* of every concrete :class:`ClaimThroughModel`
subclass — that it declares a ``claim_relationship_spec`` whose fields resolve
and whose subject + identity members match a uniqueness constraint. Deliberately
**DB-free** (no row queries), because system checks run around ``migrate`` on a
possibly-tableless database; every fact comes from ``_meta`` and the spec.

The spec drives both the validation schema and the resolution projection;
this check is the loud startup gate so a missing or drifted spec fails at
``manage.py check`` rather than silently at resolve time. Mirrors the
project idiom of a pure classifier over a facts bundle (see
``apps.core.checks._classify_soft_delete``) so each failure mode is unit-testable
with synthetic facts rather than fabricated Django models.

The XOR ``CheckConstraint`` semantics (``model XOR series``) are **not** verified
here — detecting them generically means walking a ``Q`` tree, and a name match
would couple this leaf to catalog constraint names. Following the ``actors``
precedent, that row/semantic guarantee is asserted by a per-model behavior test
instead. This check verifies only the two conditional UCs' shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple, assert_never

from django.apps.config import AppConfig
from django.core.checks import CheckMessage, Error, Tags, register
from django.db.models import Q, UniqueConstraint

from apps.core.types import ColumnName

from .claim_relationships import (
    ClaimRelationshipSpec,
    SingleSubject,
    SubjectSpec,
    XorSubject,
)
from .models import ClaimThroughModel


class _UniqueShape(NamedTuple):
    """One uniqueness rule on a through-model, reduced to what the identity
    cross-check needs: its field-set and its ``condition`` (``None`` for an
    unconditional ``UniqueConstraint`` or a ``unique_together`` entry)."""

    fields: frozenset[ColumnName]
    condition: Q | None


class _ThroughModelFacts(NamedTuple):
    """Everything :func:`_classify_through_model` needs about one through-model.

    Projected from ``_meta`` + the model's ``claim_relationship_spec`` ClassVar by
    :func:`_project_through_model_facts`, so the classifier stays a pure,
    single-argument function over plain data — testable without fabricating
    Django models.
    """

    label: str
    spec: ClaimRelationshipSpec | None
    field_names: frozenset[ColumnName]
    uniques: tuple[_UniqueShape, ...]


def _subject_fks(subject: SubjectSpec) -> tuple[ColumnName, ...]:
    """The subject FK name(s): one for ``SingleSubject``, two for ``XorSubject``."""
    # Exhaustive dispatch over the closed SubjectSpec union; assert_never makes
    # mypy flag both this site and _classify_uniqueness the moment a new variant
    # joins the union.
    match subject:
        case SingleSubject(fk_name):
            return (fk_name,)
        case XorSubject(left_fk, right_fk):
            return (left_fk, right_fk)
        case _:
            assert_never(subject)


def _project_through_model_facts(
    model: type[ClaimThroughModel],
) -> _ThroughModelFacts:
    """Gather one through-model's spec, resolvable fields and uniqueness shapes."""
    spec = getattr(model, "claim_relationship_spec", None)
    if not isinstance(spec, ClaimRelationshipSpec):
        spec = None
    field_names = frozenset(f.name for f in model._meta.get_fields())
    uniques = tuple(
        _UniqueShape(frozenset(c.fields), c.condition)
        for c in model._meta.constraints
        if isinstance(c, UniqueConstraint)
    ) + tuple(
        _UniqueShape(frozenset(group), None) for group in model._meta.unique_together
    )
    return _ThroughModelFacts(
        label=model._meta.label,
        spec=spec,
        field_names=field_names,
        uniques=uniques,
    )


def _classify_through_model(facts: _ThroughModelFacts) -> list[CheckMessage]:
    """Pure relationship-spec classifier — the testable core of the system check."""
    label, spec = facts.label, facts.spec
    if spec is None:
        return [
            Error(
                f"{label} inherits ClaimThroughModel but declares no "
                "``claim_relationship_spec``.",
                obj=label,
                id="provenance.E001",
            )
        ]

    errors: list[CheckMessage] = []
    allowed_member_counts = (1, 2) if spec.member_xor is None else (2, 3)
    if len(spec.members) not in allowed_member_counts:
        errors.append(
            Error(
                f"{label}: claim_relationship_spec.members must have "
                f"{' or '.join(map(str, allowed_member_counts))} entries "
                f"({'with' if spec.member_xor else 'without'} member_xor), "
                f"got {len(spec.members)}.",
                obj=label,
                id="provenance.E002",
            )
        )

    referenced = (
        *_subject_fks(spec.subject),
        *(m.field for m in spec.members),
        *(p.field for p in spec.payload),
    )
    missing = tuple(name for name in referenced if name not in facts.field_names)
    if missing:
        # Without resolvable fields the identity/uniqueness checks are meaningless.
        errors.append(
            Error(
                f"{label}: claim_relationship_spec references field(s) "
                f"{', '.join(missing)} that do not resolve on the model.",
                obj=label,
                id="provenance.E003",
            )
        )
        return errors

    for member in spec.members:
        if member.identity is None:
            continue
        effective_value_key = member.value_key or member.field
        if member.identity != effective_value_key:
            errors.append(
                Error(
                    f"{label}: member {member.field!r} declares "
                    f"identity={member.identity!r}, which must equal its value key "
                    f"{effective_value_key!r}.",
                    obj=label,
                    id="provenance.E004",
                )
            )

    if spec.member_xor is not None:
        errors.extend(_classify_member_xor(label, spec))
    identity_fields = frozenset(m.field for m in spec.members if m.identity is not None)
    errors.extend(
        _classify_uniqueness(
            label,
            spec.subject,
            identity_fields,
            facts.uniques,
            has_member_xor=spec.member_xor is not None,
        )
    )
    return errors


def _classify_member_xor(label: str, spec: ClaimRelationshipSpec) -> list[CheckMessage]:
    """Shape-check a ``member_xor`` declaration against the spec's members.

    Verifies the groups partition a subset of the spec's members (identity or
    not — a non-identity member may anchor an XOR rung; payload and unknown
    names may not) and that the spec's subject is a ``SingleSubject`` (no use
    case pairs a member ladder with a subject XOR, so we stay strict). Like
    the credit subject-XOR, the *row* semantics (the CHECK constraint) are
    asserted by a per-model behavior test, not here.
    """
    assert spec.member_xor is not None
    errors: list[CheckMessage] = []
    if not isinstance(spec.subject, SingleSubject):
        errors.append(
            Error(
                f"{label}: member_xor requires a SingleSubject spec.",
                obj=label,
                id="provenance.E007",
            )
        )
    groups = spec.member_xor.groups
    if len(groups) < 2:
        errors.append(
            Error(
                f"{label}: member_xor must declare at least 2 groups, "
                f"got {len(groups)}.",
                obj=label,
                id="provenance.E007",
            )
        )
    member_fields = frozenset(m.field for m in spec.members)
    seen: set[ColumnName] = set()
    for group in groups:
        for field in group:
            if field not in member_fields:
                errors.append(
                    Error(
                        f"{label}: member_xor names {field!r}, which is not a "
                        "member of the spec.",
                        obj=label,
                        id="provenance.E007",
                    )
                )
            elif field in seen:
                errors.append(
                    Error(
                        f"{label}: member_xor groups overlap on {field!r}.",
                        obj=label,
                        id="provenance.E007",
                    )
                )
            seen.add(field)
    return errors


def _classify_uniqueness(
    label: str,
    subject: SubjectSpec,
    identity_fields: frozenset[ColumnName],
    uniques: tuple[_UniqueShape, ...],
    *,
    has_member_xor: bool = False,
) -> list[CheckMessage]:
    """Cross-check the claim identity against the model's uniqueness constraints.

    ``SingleSubject``: ``{subject FK} ∪ identity`` must equal some *unconditional*
    ``UniqueConstraint`` or ``unique_together`` entry. ``XorSubject``: each branch
    needs its own *conditional* ``UniqueConstraint`` whose fields are
    ``{branch FK} ∪ identity`` and whose condition is ``Q(<branch FK>__isnull=
    False)`` — built from the spec, compared by ``Q.__eq__``, so no constraint
    name is hardcoded.

    ``member_xor`` specs have nullable identity columns, where a single
    unconditional constraint can't dedupe (NULLs compare distinct), so the model
    carries one *conditional* ``UniqueConstraint`` per ladder rung instead. The
    rung conditions are per-model semantics this DB-free check can't derive, so
    it verifies only the shape: every conditional constraint's fields must
    include the subject FK and stay within ``{subject FK} ∪ identity``, and
    their union must cover the whole identity. Rung semantics are asserted by
    the model's behavior test, like the credit XOR ``CheckConstraint``.
    """
    match subject:
        case SingleSubject(fk_name) if has_member_xor:
            expected = frozenset({fk_name}) | identity_fields
            conditional = tuple(u for u in uniques if u.condition is not None)
            covered: frozenset[ColumnName] = frozenset()
            for u in conditional:
                if fk_name not in u.fields or not u.fields <= expected:
                    return [
                        Error(
                            f"{label}: conditional UniqueConstraint "
                            f"({_fmt(u.fields)}) must include the subject FK and "
                            f"stay within the claim identity ({_fmt(expected)}).",
                            obj=label,
                            id="provenance.E008",
                        )
                    ]
                covered |= u.fields
            if covered != expected:
                return [
                    Error(
                        f"{label}: conditional UniqueConstraints cover "
                        f"({_fmt(covered)}) but the claim identity is "
                        f"({_fmt(expected)}) — every identity member must appear "
                        "in some rung constraint.",
                        obj=label,
                        id="provenance.E008",
                    )
                ]
            return []
        case SingleSubject(fk_name):
            expected = frozenset({fk_name}) | identity_fields
            if any(u.fields == expected and u.condition is None for u in uniques):
                return []
            return [
                Error(
                    f"{label}: no unconditional UniqueConstraint or unique_together "
                    f"covers the claim identity ({_fmt(expected)}) — subject FK plus "
                    "identity members.",
                    obj=label,
                    id="provenance.E005",
                )
            ]
        case XorSubject(left_fk, right_fk):
            errors: list[CheckMessage] = []
            for branch_fk in (left_fk, right_fk):
                expected = frozenset({branch_fk}) | identity_fields
                want = Q(**{f"{branch_fk}__isnull": False})
                if any(u.fields == expected and u.condition == want for u in uniques):
                    continue
                errors.append(
                    Error(
                        f"{label}: no conditional UniqueConstraint covers the "
                        f"{branch_fk!r} branch ({_fmt(expected)}) guarded by "
                        f"{branch_fk}__isnull=False.",
                        obj=label,
                        id="provenance.E006",
                    )
                )
            return errors
        case _:
            assert_never(subject)


def _fmt(fields: frozenset[ColumnName]) -> str:
    return ", ".join(sorted(fields))


@register(Tags.models)
def check_claim_through_models(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401  # Django check-framework signature
) -> list[CheckMessage]:
    """Validate every concrete ``ClaimThroughModel`` subclass.

    Walks ``__subclasses__()`` (every subclass incl. abstract intermediates and
    test stubs), not ``apps.get_models()`` (the registry walk ``relationships_for``
    uses), because a shape check must catch a malformed subclass even if
    unregistered — the same split as ``apps.core.checks`` vs
    ``apps.core.entity_types``.
    """
    _ = app_configs, kwargs
    errors: list[CheckMessage] = []
    visited: set[type[ClaimThroughModel]] = set()

    def walk(cls: type[ClaimThroughModel]) -> None:
        for subclass in cls.__subclasses__():
            if subclass in visited:
                continue
            visited.add(subclass)
            walk(subclass)
            if subclass._meta.abstract:
                continue
            errors.extend(
                _classify_through_model(_project_through_model_facts(subclass))
            )

    # ``ClaimThroughModel`` is abstract; ``__subclasses__()`` is the walk entry
    # point (same pattern as ``check_actor_models`` / ``check_linkable_models``).
    walk(ClaimThroughModel)  # type: ignore[type-abstract]
    return errors
