"""Domain-agnostic interactive claim-write engine.

The generic core of the PATCH claims path: validate scalar fields, then
write a list of :class:`ClaimSpec` atomically as an attributed ChangeSet,
attach citations and trigger resolution. Binds the loose
``ClaimControlledModel`` — its caller has already resolved the row, so it
needs nothing about addressing.

The concrete, per-relationship spec-builders that feed it ``ClaimSpec``s
live alongside the domain endpoints in :mod:`apps.catalog.api.edit_claims`.
This module imports no catalog symbol at all; the app-layer spine enforces
``claim_edit ⊄ catalog``, keeping the engine a generic write surface
reusable across domains. See docs/AppBoundaries.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple, NoReturn, cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.exceptions import StructuredValidationError
from apps.provenance.changeset_writer import record_changeset
from apps.provenance.claim_writer import _assert_claim
from apps.provenance.models import (
    ChangeSet,
    ChangeSetAction,
    CitationInstance,
    Claim,
    ClaimControlledModel,
    get_claim_fields,
)
from apps.provenance.resolution import resolve_after_mutation
from apps.provenance.schemas import CitationReferenceInputSchema
from apps.provenance.validation import validate_claim_value

__all__ = [
    "ClaimSpec",
    "EntityClaims",
    "ValidationErrors",
    "raise_form_error",
    "plan_scalar_field_claims",
    "validate_scalar_fields",
    "execute_claims",
    "execute_multi_entity_claims",
]

# ``request.user`` is typed as ``AbstractBaseUser | AnonymousUser``; callers
# narrow at the entry points below before threading into the internal helper.
_RequestUser = AbstractBaseUser | AnonymousUser


def _narrow_to_user(user: _RequestUser) -> User:
    """Narrow a ``request.user`` to the concrete ``User`` for ``ChangeSet.user``.

    All callers sit behind ``auth=django_auth``, so an anonymous user can't
    reach the write helpers. Narrow so ``ChangeSet.user`` (NOT NULL) isn't
    handed an ``AnonymousUser`` whose ``pk`` is ``None``. The runtime check
    only excludes ``AnonymousUser`` (the actual invariant) so it stays correct
    if ``AUTH_USER_MODEL`` is ever swapped.

    The ``cast(User, user)`` is a django-stubs workaround: the FK to
    ``settings.AUTH_USER_MODEL`` is typed against ``auth.User`` while
    ``request.user`` is ``AbstractBaseUser | AnonymousUser``. Both the cast and
    the tripwire go away if/when the project swaps in a custom User model that
    django-stubs can track directly.
    """
    assert not isinstance(user, AnonymousUser)
    return cast(User, user)


@dataclass(frozen=True)
class ClaimSpec:
    """A planned claim to be written — separates diffing from execution."""

    field_name: str
    # Claim values are intentionally polymorphic (str | int | bool | dict for
    # relationship claims | None); ``object`` is the accurate type, and
    # consumers narrow per field_name before persisting.
    value: object
    claim_key: str = ""


class EntityClaims(NamedTuple):
    """One entity paired with the claims to assert on it.

    The unit of work for :func:`execute_multi_entity_claims`, where several
    entities are written in a single ChangeSet (e.g. a cascading soft-delete).
    """

    entity: ClaimControlledModel
    specs: list[ClaimSpec]


@dataclass
class ValidationErrors:
    """Accumulates field-level and form-level errors, then raises once.

    Structured error responses let the frontend display errors inline
    next to the offending field instead of a single banner string.
    """

    field_errors: dict[str, str] = field(default_factory=dict)
    form_errors: list[str] = field(default_factory=list)

    def add_field(self, field_name: str, message: str) -> None:
        # First writer wins: later checks (e.g. unknown-person) must not
        # silently clobber an earlier, more specific error on the same field.
        self.field_errors.setdefault(field_name, message)

    def add_form(self, message: str) -> None:
        self.form_errors.append(message)

    @property
    def has_errors(self) -> bool:
        return bool(self.field_errors) or bool(self.form_errors)

    def raise_if_errors(self) -> None:
        if not self.has_errors:
            return
        parts = list(self.field_errors.values()) + self.form_errors
        raise StructuredValidationError(
            message="; ".join(parts),
            field_errors=self.field_errors,
            form_errors=self.form_errors,
        )


def raise_form_error(message: str) -> NoReturn:
    """Raise a structured 422 for a form-level (non-field) error."""
    raise StructuredValidationError(
        message=message,
        form_errors=[message],
    )


def plan_scalar_field_claims[M: ClaimControlledModel](
    model_class: type[M],
    fields: dict[str, Any],
    *,
    entity: M | None = None,
) -> list[ClaimSpec]:
    """Validate scalar fields and reject empty/no-op field payloads.

    Shared by PATCH endpoints that only accept scalar ``fields`` payloads.
    """
    if not fields:
        raise_form_error("No changes provided.")

    specs = validate_scalar_fields(model_class, fields, entity=entity)
    if not specs:
        raise_form_error("No changes provided.")
    return specs


def validate_scalar_fields[M: ClaimControlledModel](
    model_class: type[M],
    fields: dict[str, Any],
    *,
    entity: M | None = None,
) -> list[ClaimSpec]:
    """Validate scalar fields and return ClaimSpecs.

    Scalar fields are assertion-based: a spec is created for every field in
    the request, even if the value matches the current state. Reasserting
    the same value is meaningful (e.g., a user confirming a machine-sourced
    value). The frontend is responsible for only sending changed fields.

    Collects all field-level errors and raises them together so the
    frontend can display every problem at once.

    Raises HttpError 422 on unknown fields or invalid values.
    """
    editable = set(get_claim_fields(model_class))
    unknown = set(fields.keys()) - editable
    if unknown:
        raise_form_error(f"Unknown or non-editable fields: {sorted(unknown)}")

    errors = ValidationErrors()
    specs: list[ClaimSpec] = []
    for field_name, value in fields.items():
        field_obj = model_class._meta.get_field(field_name)
        # Claim.value is NOT NULL; store allowed clears as "" and let the
        # resolver coerce that sentinel back to None/blank based on field
        # metadata. Required fields must reject clears up front.
        if value is None:
            if not (field_obj.null or getattr(field_obj, "blank", False)):
                errors.add_field(field_name, "This field cannot be cleared.")
                continue
            value = ""
        try:
            value = validate_claim_value(field_name, value, model_class)
        except ValidationError as exc:
            errors.add_field(field_name, "; ".join(exc.messages))
            continue
        if getattr(field_obj, "unique", False) and value != "":
            conflict_qs = model_class._default_manager.filter(**{field_name: value})
            if entity is not None and getattr(entity, "pk", None) is not None:
                conflict_qs = conflict_qs.exclude(pk=entity.pk)
            if conflict_qs.exists():
                errors.add_field(field_name, "This value must be unique.")
                continue
        specs.append(ClaimSpec(field_name=field_name, value=value))

    errors.raise_if_errors()
    return specs


def _write_claims_in_changeset(
    entity: ClaimControlledModel,
    specs: list[ClaimSpec],
    *,
    changeset: ChangeSet,
) -> list[Claim]:
    """Assert claims on *entity* inside an already-open *changeset*.

    Does not open a transaction, create a ChangeSet, attach citations, or
    resolve. The caller is responsible for all of that. Returns the list of
    newly-created active Claim rows so the caller can attach citations.
    Attribution rides on ``changeset.actor``.
    """
    created_claims: list[Claim] = []
    for spec in specs:
        created_claims.append(
            _assert_claim(
                entity,
                spec.field_name,
                spec.value,
                claim_key=spec.claim_key,
                changeset=changeset,
            )
        )
    return created_claims


def _attach_citation(
    claims: list[Claim],
    citation: CitationReferenceInputSchema | None,
) -> None:
    """Link each claim in *claims* to a copy of the referenced citation instance."""
    if citation is None:
        return
    try:
        template = CitationInstance.objects.select_related("citation_source").get(
            pk=citation.citation_instance_id
        )
    except CitationInstance.DoesNotExist:
        raise_form_error("Unknown citation instance.")

    for claim in claims:
        instance = CitationInstance(
            citation_source=template.citation_source,
            claim=claim,
            locator=template.locator,
        )
        # slug is assigned in CitationInstance.save(); exclude it from
        # validation, which runs first and would otherwise see it blank.
        instance.full_clean(exclude=["slug"])
        instance.save()


def execute_claims(
    entity: ClaimControlledModel,
    specs: list[ClaimSpec],
    *,
    user: _RequestUser,
    action: ChangeSetAction = ChangeSetAction.EDIT,
    note: str = "",
    citation: CitationReferenceInputSchema | None = None,
) -> None:
    """Create a ChangeSet + claims atomically, resolve, and invalidate cache.

    Resolution is handled by :func:`resolve_after_mutation` which routes
    to the correct resolver(s) based on entity type and the claim field
    names in *specs*.

    Raises HttpError 422 on IntegrityError (unique constraint violations).
    """
    auth_user = _narrow_to_user(user)
    try:
        with transaction.atomic():
            cs = record_changeset(actor=auth_user.actor, action=action, note=note)
            created_claims = _write_claims_in_changeset(entity, specs, changeset=cs)
            _attach_citation(created_claims, citation)
            field_names = list({s.field_name for s in specs})
            resolve_after_mutation(entity, field_names=field_names)
    except ValidationError as exc:
        raise_form_error("; ".join(exc.messages))
    except IntegrityError as exc:
        raise_form_error(f"Unique constraint violation: {exc}")


def execute_multi_entity_claims(
    entries: Sequence[EntityClaims],
    *,
    user: _RequestUser,
    action: ChangeSetAction,
    note: str = "",
    citation: CitationReferenceInputSchema | None = None,
) -> ChangeSet:
    """Write claims spanning multiple entities inside a single ChangeSet.

    Used by cascading operations (e.g. soft-delete a Title + each of its
    active MachineModels) where the unit of work must appear as one action
    in edit history and be inverted as one unit by Undo.

    One ChangeSet is created with the given *action*; each entry's claims are
    asserted within that changeset; the *citation* (if any) is attached to
    every created claim across all entities; finally ``resolve_after_mutation``
    is invoked per entity for just the fields that entity touched.

    Returns the created ChangeSet so callers can thread its id into the
    response (Undo needs it).
    """
    auth_user = _narrow_to_user(user)
    try:
        with transaction.atomic():
            cs = record_changeset(actor=auth_user.actor, action=action, note=note)
            all_created: list[Claim] = []
            per_entity_fields: list[tuple[ClaimControlledModel, list[str]]] = []
            for entity, specs in entries:
                if not specs:
                    continue
                created = _write_claims_in_changeset(entity, specs, changeset=cs)
                all_created.extend(created)
                per_entity_fields.append((entity, list({s.field_name for s in specs})))
            _attach_citation(all_created, citation)
            for entity, field_names in per_entity_fields:
                resolve_after_mutation(entity, field_names=field_names)
    except ValidationError as exc:
        raise_form_error("; ".join(exc.messages))
    except IntegrityError as exc:
        raise_form_error(f"Unique constraint violation: {exc}")
    return cs
