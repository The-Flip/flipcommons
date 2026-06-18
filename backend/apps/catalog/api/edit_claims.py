"""Shared helpers for PATCH claims endpoints.

Provides the plan/execute pattern for entity editing: validate input,
build a list of ClaimSpecs, then execute them atomically in a ChangeSet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn, cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, transaction
from django.db import models as db_models
from ninja import Schema

from apps.accounts.models import User
from apps.catalog.exceptions import StructuredValidationError
from apps.catalog.models import (
    CorporateEntity,
    CreditRole,
    GameplayFeature,
    Location,
    MachineModel,
    Person,
    Theme,
    Title,
)
from apps.core.models import SluggedModel
from apps.provenance.claims import (
    build_relationship_claim,
    normalize_abbreviation_value,
    normalize_alias_identity,
)
from apps.provenance.models import (
    ChangeSet,
    ChangeSetAction,
    CitationInstance,
    Claim,
    ClaimControlledModel,
    get_claim_fields,
)
from apps.provenance.schemas import CitationReferenceInputSchema
from apps.provenance.validation import get_relationship_schema, validate_claim_value

from ..resolve import resolve_after_mutation
from ._typing import CreditKey, CreditPkKey
from .schemas import CreditInputSchema, GameplayFeatureInputSchema

# ``request.user`` is typed as ``AbstractBaseUser | AnonymousUser``; callers
# narrow at the entry points below before threading into the internal helper.
_RequestUser = AbstractBaseUser | AnonymousUser

# Concrete catalog models with a self-referencing ``parents`` M2M / reverse
# ``aliases`` relation, typed as unions rather than a structural protocol
# because the two helpers are only called from a handful of sites.
_ParentEntity = GameplayFeature | Theme
_AliasEntity = GameplayFeature | Theme | CorporateEntity | Location


@dataclass(frozen=True)
class ClaimSpec:
    """A planned claim to be written — separates diffing from execution."""

    field_name: str
    # Claim values are intentionally polymorphic (str | int | bool | dict for
    # relationship claims | None); ``object`` is the accurate type, and
    # consumers narrow per field_name before persisting.
    value: object
    claim_key: str = ""


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


class FieldConstraintSchema(Schema):
    """Numeric validator-derived constraint for a single field.

    The endpoint serializes with ``exclude_none=True`` so ``min`` / ``max``
    keys are omitted when unbounded rather than sent as ``null``.
    """

    min: float | int | None = None
    max: float | int | None = None
    step: float | int


def get_field_constraints(
    model_class: type[ClaimControlledModel],
) -> dict[str, FieldConstraintSchema]:
    """Extract min/max/step constraints from numeric claim fields.

    Only fields with at least one validator-derived bound are included.
    Step is derived from ``DecimalField.decimal_places``.
    """
    numeric_types = (
        db_models.IntegerField,
        db_models.SmallIntegerField,
        db_models.PositiveIntegerField,
        db_models.PositiveSmallIntegerField,
        db_models.DecimalField,
        db_models.FloatField,
    )
    editable = get_claim_fields(model_class)
    constraints: dict[str, FieldConstraintSchema] = {}

    for field_name in editable:
        field = model_class._meta.get_field(field_name)
        if not isinstance(field, numeric_types):
            continue

        bounds: dict[str, float | int] = {}
        # Use _validators (explicitly declared) rather than .validators
        # (which includes DB-range validators like max=9223372036854775807).
        for v in cast(list[object], getattr(field, "_validators", [])):
            if isinstance(v, MinValueValidator):
                bounds["min"] = v.limit_value
            elif isinstance(v, MaxValueValidator):
                bounds["max"] = v.limit_value

        if not bounds:
            continue
        if isinstance(field, db_models.DecimalField) and field.decimal_places:
            step: float | int = float(f"1e-{field.decimal_places}")
        else:
            step = 1
        constraints[field_name] = FieldConstraintSchema(**bounds, step=step)

    return constraints


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


def plan_parent_claims(
    entity: _ParentEntity,
    desired_slugs: set[str],
    *,
    model_class: type[_ParentEntity],
    claim_field_name: str,
) -> list[ClaimSpec]:
    """Validate parent hierarchy changes and return diff-based ClaimSpecs.

    Works for any model with a self-referencing ``parents`` M2M resolved
    via relationship claims (GameplayFeature, Theme).

    Raises HttpError 422 on invalid slugs, self-links, or cycles.
    """
    if entity.slug in desired_slugs:
        raise_form_error(f"A {model_class.__name__} cannot be its own parent.")

    # Resolve desired slugs → PKs (also validates existence).
    slug_to_pk = dict(
        model_class._default_manager.filter(slug__in=desired_slugs).values_list(
            "slug", "pk"
        )
    )
    missing = desired_slugs - slug_to_pk.keys()
    if missing:
        raise_form_error(f"Unknown parent slugs: {sorted(missing)}")

    # Cycle detection: for each proposed parent, walk up the existing
    # graph (excluding the edited entity's current parents, since
    # they're being replaced). If we reach the edited entity, reject.
    if desired_slugs:
        all_entities = model_class._default_manager.prefetch_related("parents").all()
        parent_map: dict[str, set[str]] = {}
        for e in all_entities:
            if e.slug == entity.slug:
                continue
            parent_map[e.slug] = {p.slug for p in e.parents.all()}

        for start_slug in desired_slugs:
            visited: set[str] = set()
            stack = [start_slug]
            while stack:
                current = stack.pop()
                if current == entity.slug:
                    raise_form_error(
                        f"Adding parent '{start_slug}' would create a cycle.",
                    )
                if current in visited:
                    continue
                visited.add(current)
                stack.extend(parent_map.get(current, set()))

    # Diff against current M2M state (by PK).
    desired_pks = set(slug_to_pk.values())
    current_pks = set(entity.parents.values_list("pk", flat=True))
    specs: list[ClaimSpec] = []
    for parent_pk in desired_pks - current_pks:
        claim_key, value = build_relationship_claim(
            claim_field_name, {"parent": parent_pk}
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    for parent_pk in current_pks - desired_pks:
        claim_key, value = build_relationship_claim(
            claim_field_name, {"parent": parent_pk}, exists=False
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    return specs


def plan_alias_claims(
    entity: _AliasEntity,
    desired_aliases: list[str],
    *,
    claim_field_name: str,
) -> list[ClaimSpec]:
    """Validate alias changes and return diff-based ClaimSpecs.

    Normalises input (strip, deduplicate by lowercase key) and diffs
    against current alias rows.  Preserves user-typed case via
    ``alias_display`` so the resolver stores the display form.

    Returns specs for adds, removes, and display-case updates.
    """
    # Normalise: strip, deduplicate by lowercase key, drop blanks.
    # Last-write-wins for display case when duplicates differ only in case.
    # The strip/lower fold is shared with the data-patch adapter via
    # ``normalize_alias_identity`` so the two paths produce identical bytes.
    desired: dict[str, str] = {}  # lowercase → display string
    for raw in desired_aliases:
        ident = normalize_alias_identity(raw)
        if ident.value:
            desired[ident.value] = ident.display

    current: dict[str, str] = {}  # lowercase → stored display string
    for a in entity.aliases.all():
        current[a.value.lower()] = a.value

    specs: list[ClaimSpec] = []
    # Adds and display-case updates
    for lower, display in desired.items():
        if lower not in current or current[lower] != display:
            claim_key, value = build_relationship_claim(
                claim_field_name,
                {"alias_value": lower, "alias_display": display},
            )
            specs.append(
                ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
            )
    # Removes
    for lower in current.keys() - desired.keys():
        claim_key, value = build_relationship_claim(
            claim_field_name, {"alias_value": lower}, exists=False
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    return specs


def plan_m2m_claims(
    entity: MachineModel,
    desired_slugs: set[str],
    *,
    target_model: type[SluggedModel],
    claim_field_name: str,
    m2m_attr: str,
) -> list[ClaimSpec]:
    """Validate and diff a simple slug-set M2M relationship.

    Works for any MachineModel M2M that is resolved by PK (themes, tags,
    reward_types).  The API receives slugs; this function resolves them to
    PKs before building claims.  Unlike ``plan_parent_claims``, no hierarchy
    or cycle checks are needed.

    Raises HttpError 422 on unknown slugs.
    """
    if desired_slugs:
        slug_to_pk = dict(
            target_model._default_manager.filter(slug__in=desired_slugs).values_list(
                "slug", "pk"
            )
        )
        missing = desired_slugs - slug_to_pk.keys()
        if missing:
            raise_form_error(f"Unknown {claim_field_name} slugs: {sorted(missing)}")
        desired_pks = set(slug_to_pk.values())
    else:
        desired_pks = set()

    current_pks = set(getattr(entity, m2m_attr).values_list("pk", flat=True))
    return build_m2m_claim_specs(
        current=current_pks,
        desired=desired_pks,
        claim_field_name=claim_field_name,
    )


def build_m2m_claim_specs(
    *,
    current: set[int],
    desired: set[int],
    claim_field_name: str,
) -> list[ClaimSpec]:
    """Build diff-based ClaimSpecs for simple PK-set M2M relationships."""
    specs: list[ClaimSpec] = []
    for pk in desired - current:
        claim_key, value = build_relationship_claim(
            claim_field_name, {claim_field_name: pk}
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    for pk in current - desired:
        claim_key, value = build_relationship_claim(
            claim_field_name, {claim_field_name: pk}, exists=False
        )
        specs.append(
            ClaimSpec(field_name=claim_field_name, value=value, claim_key=claim_key)
        )
    return specs


def normalize_gameplay_feature_inputs(
    desired_features: list[tuple[str, int | None]],
    *,
    available_slugs: set[str] | None = None,
) -> dict[str, int | None]:
    """Normalize gameplay feature input into a slug->count map.

    Duplicate slugs are rejected. Counts, when provided, must be positive.
    When ``available_slugs`` is provided, unknown slugs are rejected without
    touching the database.

    Field errors are keyed ``gameplay_features.{slug}`` so the frontend can
    display them inline on the corresponding row.
    """
    errors = ValidationErrors()
    desired: dict[str, int | None] = {}
    for slug, count in desired_features:
        if slug in desired:
            errors.add_field(f"gameplay_features.{slug}", "Duplicate feature.")
            continue
        if count is not None and count <= 0:
            errors.add_field(
                f"gameplay_features.{slug}", f"Count must be positive, got {count}."
            )
            continue
        desired[slug] = count

    if available_slugs is not None:
        for slug in set(desired.keys()) - available_slugs:
            errors.add_field(f"gameplay_features.{slug}", "Unknown gameplay feature.")

    errors.raise_if_errors()
    return desired


def build_gameplay_feature_claim_specs(
    current: dict[int, int | None],
    desired: dict[int, int | None],
) -> list[ClaimSpec]:
    """Build diff-based ClaimSpecs for gameplay feature relationship changes."""
    specs: list[ClaimSpec] = []
    for pk, count in desired.items():
        if pk not in current or current[pk] != count:
            claim_key, value = build_relationship_claim(
                "gameplay_feature", {"gameplay_feature": pk}
            )
            value["count"] = count
            specs.append(
                ClaimSpec(
                    field_name="gameplay_feature",
                    value=value,
                    claim_key=claim_key,
                )
            )
    for pk in current.keys() - desired.keys():
        claim_key, value = build_relationship_claim(
            "gameplay_feature", {"gameplay_feature": pk}, exists=False
        )
        specs.append(
            ClaimSpec(
                field_name="gameplay_feature",
                value=value,
                claim_key=claim_key,
            )
        )
    return specs


def plan_gameplay_feature_claims(
    entity: MachineModel,
    desired_features: list[GameplayFeatureInputSchema],
) -> list[ClaimSpec]:
    """Validate and diff gameplay features (slug + optional count) on a MachineModel.

    Each entry has a ``slug`` and optional ``count``.  Duplicate slugs in the
    input are rejected.  Count must be positive if provided.

    Assumes ``entity`` has a ``machinemodelgameplayfeature_set`` reverse
    relation (i.e., is a MachineModel with that through-table prefetched).

    Raises HttpError 422 on invalid input.
    """
    raw_desired = [(feat.slug, feat.count) for feat in desired_features]
    if raw_desired:
        existing = set(
            GameplayFeature.objects.filter(
                slug__in={slug for slug, _ in raw_desired}
            ).values_list("slug", flat=True)
        )
        desired = normalize_gameplay_feature_inputs(
            raw_desired, available_slugs=existing
        )
    else:
        desired = normalize_gameplay_feature_inputs(raw_desired)

    # Resolve slugs → PKs.
    slug_to_pk = dict(
        GameplayFeature.objects.filter(slug__in=desired.keys()).values_list(
            "slug", "pk"
        )
    )
    desired_by_pk: dict[int, int | None] = {
        slug_to_pk[slug]: count for slug, count in desired.items()
    }

    # Current state from prefetched through-table (by PK).
    current_by_pk: dict[int, int | None] = {}
    for row in entity.machinemodelgameplayfeature_set.all():
        current_by_pk[row.gameplayfeature_id] = row.count

    return build_gameplay_feature_claim_specs(current_by_pk, desired_by_pk)


def plan_abbreviation_claims(
    entity: MachineModel | Title,
    desired_values: list[str],
) -> list[ClaimSpec]:
    """Validate and diff abbreviation changes.

    Normalises input (strip, deduplicate, drop blanks, enforce max length)
    and diffs against current abbreviation rows.

    Shared by MachineModel and Title.
    """
    desired = set(_normalize_abbreviations(desired_values))
    current = set(entity.abbreviations.values_list("value", flat=True))
    specs: list[ClaimSpec] = []

    for value in desired - current:
        claim_key, claim_value = build_relationship_claim(
            "abbreviation", {"value": value}
        )
        specs.append(
            ClaimSpec(field_name="abbreviation", value=claim_value, claim_key=claim_key)
        )

    for value in current - desired:
        claim_key, claim_value = build_relationship_claim(
            "abbreviation", {"value": value}, exists=False
        )
        specs.append(
            ClaimSpec(field_name="abbreviation", value=claim_value, claim_key=claim_key)
        )
    return specs


def plan_credit_claims(
    entity: MachineModel,
    desired_credits: list[CreditInputSchema],
) -> list[ClaimSpec]:
    """Validate and diff credits (person_slug + role) on a MachineModel.

    Each entry has a ``person_slug`` and ``role`` (role slug).  Duplicate
    (person_slug, role) pairs in the input are rejected.

    Assumes ``entity`` has ``credits`` prefetched with
    select_related("person", "role").

    Raises HttpError 422 on invalid input.
    """
    raw_desired = [
        CreditKey(credit.person_slug, credit.role) for credit in desired_credits
    ]

    if raw_desired:
        desired_person_slugs = {p for p, _ in raw_desired}
        existing_people = set(
            Person.objects.filter(slug__in=desired_person_slugs).values_list(
                "slug", flat=True
            )
        )
        desired_role_slugs = {r for _, r in raw_desired}
        existing_roles = set(
            CreditRole.objects.filter(slug__in=desired_role_slugs).values_list(
                "slug", flat=True
            )
        )
        desired = normalize_credit_inputs(
            raw_desired,
            available_people=existing_people,
            available_roles=existing_roles,
        )
    else:
        desired = normalize_credit_inputs(raw_desired)

    # Resolve slugs → PKs for claim building.
    if desired:
        person_slug_to_pk = dict(
            Person.objects.filter(slug__in={p for p, _ in desired}).values_list(
                "slug", "pk"
            )
        )
        role_slug_to_pk = dict(
            CreditRole.objects.filter(slug__in={r for _, r in desired}).values_list(
                "slug", "pk"
            )
        )
        desired_pks: set[CreditPkKey] = {
            CreditPkKey(person_slug_to_pk[p], role_slug_to_pk[r]) for p, r in desired
        }
    else:
        desired_pks = set()

    # Current state from prefetched credits (by PK).
    current_pks: set[CreditPkKey] = set()
    for credit in entity.credits.all():
        current_pks.add(CreditPkKey(credit.person_id, credit.role_id))

    return build_credit_claim_specs(current_pks, desired_pks)


def normalize_credit_inputs(
    desired_credits: list[CreditKey],
    *,
    available_people: set[str] | None = None,
    available_roles: set[str] | None = None,
) -> set[CreditKey]:
    """Normalize credits into unique (person_slug, role_slug) pairs.

    When available slug sets are provided, unknown people or roles are rejected
    without touching the database.

    Field errors are keyed ``credits.{person_slug}:{role}`` so the frontend
    can display them inline on the corresponding row.
    """
    errors = ValidationErrors()
    desired: set[CreditKey] = set()
    for person_slug, role in desired_credits:
        pair = CreditKey(person_slug, role)
        if pair in desired:
            errors.add_field(f"credits.{person_slug}:{role}", "Duplicate credit.")
            continue
        desired.add(pair)

    if available_people is not None:
        missing_people = {p for p, _ in desired} - available_people
        if missing_people:
            for person_slug, role in desired:
                if person_slug in missing_people:
                    errors.add_field(
                        f"credits.{person_slug}:{role}",
                        f"Unknown person: {person_slug}.",
                    )

    if available_roles is not None:
        missing_roles = {r for _, r in desired} - available_roles
        if missing_roles:
            for person_slug, role in desired:
                if role in missing_roles:
                    errors.add_field(
                        f"credits.{person_slug}:{role}",
                        f"Unknown role: {role}.",
                    )

    errors.raise_if_errors()
    return desired


def build_credit_claim_specs(
    current: set[CreditPkKey],
    desired: set[CreditPkKey],
) -> list[ClaimSpec]:
    """Build diff-based ClaimSpecs for credit relationship changes."""
    specs: list[ClaimSpec] = []
    for person_pk, role_pk in desired - current:
        claim_key, value = build_relationship_claim(
            "credit", {"person": person_pk, "role": role_pk}
        )
        specs.append(ClaimSpec(field_name="credit", value=value, claim_key=claim_key))
    for person_pk, role_pk in current - desired:
        claim_key, value = build_relationship_claim(
            "credit", {"person": person_pk, "role": role_pk}, exists=False
        )
        specs.append(ClaimSpec(field_name="credit", value=value, claim_key=claim_key))
    return specs


def _abbreviation_max_length() -> int:
    """The abbreviation length bound, read from the registered schema.

    Model-derived (populated from the through-model ``CharField`` at
    registration), so the editor and the data-patch adapter enforce the same
    limit from one source instead of a hardcoded constant.
    """
    schema = get_relationship_schema("abbreviation")
    assert schema is not None, "abbreviation schema must be registered"
    (spec,) = [s for s in schema.value_keys if s.identity is not None]
    assert spec.max_length is not None, "abbreviation identity must declare max_length"
    return spec.max_length


def _normalize_abbreviations(values: list[str]) -> list[str]:
    """Strip, deduplicate, drop blanks, enforce max length.

    The strip fold is shared with the data-patch adapter via
    ``normalize_abbreviation_value`` and the length bound comes from the
    registered schema (``_abbreviation_max_length``), so both write paths
    normalize and bound identically.
    """
    max_length = _abbreviation_max_length()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = normalize_abbreviation_value(raw_value)
        if not value:
            continue
        if len(value) > max_length:
            raise_form_error(f"Abbreviations must be {max_length} characters or fewer.")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _write_claims_in_changeset(
    entity: ClaimControlledModel,
    specs: list[ClaimSpec],
    *,
    user: User,
    changeset: ChangeSet,
) -> list[Claim]:
    """Assert claims on *entity* inside an already-open *changeset*.

    Does not open a transaction, create a ChangeSet, attach citations, or
    resolve. The caller is responsible for all of that. Returns the list of
    newly-created active Claim rows so the caller can attach citations.
    """
    created_claims: list[Claim] = []
    for spec in specs:
        created_claims.append(
            Claim.objects.assert_claim(
                entity,
                spec.field_name,
                spec.value,
                user=user,
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
    # All callers sit behind ``auth=django_auth``, so an anonymous user can't
    # reach this helper. Narrow so ``ChangeSet.user`` (NOT NULL) isn't handed
    # an ``AnonymousUser`` whose ``pk`` is ``None``. The runtime check only
    # excludes ``AnonymousUser`` (the actual invariant) so it stays correct
    # if ``AUTH_USER_MODEL`` is ever swapped.
    #
    # The ``cast(User, user)`` at the ``create`` call is a django-stubs
    # workaround: the FK to ``settings.AUTH_USER_MODEL`` is typed against
    # ``auth.User`` while ``request.user`` is ``AbstractBaseUser |
    # AnonymousUser``. Both the cast and the tripwire go away if/when the
    # project swaps in a custom User model that django-stubs can track directly.
    assert not isinstance(user, AnonymousUser)
    auth_user = cast(User, user)
    try:
        with transaction.atomic():
            cs = ChangeSet.objects.create(user=auth_user, action=action, note=note)
            created_claims = _write_claims_in_changeset(
                entity, specs, user=auth_user, changeset=cs
            )
            _attach_citation(created_claims, citation)
            field_names = list({s.field_name for s in specs})
            resolve_after_mutation(entity, field_names=field_names)
    except ValidationError as exc:
        raise_form_error("; ".join(exc.messages))
    except IntegrityError as exc:
        raise_form_error(f"Unique constraint violation: {exc}")


def execute_multi_entity_claims(
    entries: Sequence[tuple[ClaimControlledModel, list[ClaimSpec]]],
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

    *entries* is a list of ``(entity, specs)`` pairs. One ChangeSet is created
    with the given *action*; each entry's claims are asserted within that
    changeset; the *citation* (if any) is attached to every created claim
    across all entities; finally ``resolve_after_mutation`` is invoked per
    entity for just the fields that entity touched.

    Returns the created ChangeSet so callers can thread its id into the
    response (Undo needs it).
    """
    # All callers sit behind ``auth=django_auth``, so an anonymous user can't
    # reach this helper. Narrow so ``ChangeSet.user`` (NOT NULL) isn't handed
    # an ``AnonymousUser`` whose ``pk`` is ``None``. The runtime check only
    # excludes ``AnonymousUser`` (the actual invariant) so it stays correct
    # if ``AUTH_USER_MODEL`` is ever swapped.
    #
    # The ``cast(User, user)`` at the ``create`` call is a django-stubs
    # workaround: the FK to ``settings.AUTH_USER_MODEL`` is typed against
    # ``auth.User`` while ``request.user`` is ``AbstractBaseUser |
    # AnonymousUser``. Both the cast and the tripwire go away if/when the
    # project swaps in a custom User model that django-stubs can track directly.
    assert not isinstance(user, AnonymousUser)
    auth_user = cast(User, user)
    try:
        with transaction.atomic():
            cs = ChangeSet.objects.create(user=auth_user, action=action, note=note)
            all_created: list[Claim] = []
            per_entity_fields: list[tuple[ClaimControlledModel, list[str]]] = []
            for entity, specs in entries:
                if not specs:
                    continue
                created = _write_claims_in_changeset(
                    entity, specs, user=auth_user, changeset=cs
                )
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
