"""Shared helpers for claim resolution: coercion, FK lookup, field defaults.

The claim winner-pick itself (priority annotation + tiebreak order) lives in
:mod:`apps.provenance.claim_ranking_in_db`, shared by every ``ClaimControlledModel``
consumer.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from django.db import models

from apps.core.models import meta_unique_fields
from apps.core.types import ClaimFieldMap, ClaimFieldName, PublicId
from apps.provenance.claims import normalize_fk_value
from apps.provenance.models import ClaimControlledModel

logger = logging.getLogger(__name__)


def validate_check_constraints(obj: models.Model) -> None:
    """Validate cross-field CheckConstraints before save/bulk_update.

    Only validates constraints tagged with ``violation_error_code`` — these
    are cross-field invariants (year ordering, month-requires-year, self-ref
    anti-cycle) that the resolver can violate by combining independent claim
    winners.  Single-field constraints (non-blank, range) are DB safety nets
    for external writes and are not checked here — the resolver legitimately
    resets unclaimed fields to defaults like ``""``.

    Skips UniqueConstraints entirely — their ``validate()`` fires a DB query
    per constraint, which is O(n * constraints) in a bulk loop.
    """
    for constraint in obj._meta.constraints:
        if not isinstance(constraint, models.CheckConstraint):
            continue

        violation_error_code = getattr(constraint, "violation_error_code", None)
        validate = getattr(constraint, "validate", None)
        if violation_error_code is not None and callable(validate):
            validate(type(obj), obj)


type FKTargetLookups = dict[str, dict[PublicId, models.Model]]
"""Per FK field, a map from a target's public_id (typically slug) to its resolved
instance — the prefetched index that turns a claimed slug into a foreign key
without a query per claim."""


@dataclass
class FKInfo:
    """FK field metadata and pre-fetched lookups for bulk resolution."""

    fk_fields: set[str] = field(default_factory=set)
    lookups: FKTargetLookups = field(default_factory=dict)


# ------------------------------------------------------------------
# Generic FK resolution (model-introspected)
# ------------------------------------------------------------------


def _resolve_fk_generic(
    model_class: type[ClaimControlledModel],
    field_name: ClaimFieldName,
    value: object,
    lookup: Mapping[str, models.Model] | None = None,
) -> models.Model | None:
    """Resolve a claim value to an FK instance by introspecting the Django field.

    Uses ``slug`` as the default lookup key on the target model.  Models can
    override this per-FK via a ``claim_fk_lookups`` class attribute::

        class Location(models.Model):
            claim_fk_lookups = {"parent": "location_path"}

    If *lookup* is provided (pre-fetched slug→instance dict), it is used
    instead of hitting the database.
    """
    key = normalize_fk_value(value)
    if key is None:
        return None

    field = model_class._meta.get_field(field_name)
    target_model = field.related_model
    if target_model is None:
        logger.warning(
            "FK field %s on %s has no related model", field_name, model_class
        )
        return None
    lookup_key = model_class.claim_fk_lookups.get(field_name, "slug")

    if lookup is not None:
        result = lookup.get(key)
    else:
        assert isinstance(target_model, type)
        assert issubclass(target_model, models.Model)
        result = target_model._default_manager.filter(**{lookup_key: key}).first()
    if not result:
        logger.warning("Unmatched %s claim value: %r", field_name, value)
    return result


def build_fk_info(
    model_class: type[ClaimControlledModel],
    claim_fields: ClaimFieldMap,
) -> FKInfo:
    """Identify FK fields and pre-build slug-to-instance lookups for bulk resolution."""
    info = FKInfo()
    for attr in claim_fields.values():
        f = model_class._meta.get_field(attr)
        if f.is_relation:
            info.fk_fields.add(attr)
            lookup_key = model_class.claim_fk_lookups.get(attr, "slug")
            target_model = f.related_model
            if target_model is None:
                continue
            assert isinstance(target_model, type)
            assert issubclass(target_model, models.Model)
            info.lookups[attr] = {
                getattr(obj, lookup_key): obj
                for obj in target_model._default_manager.all()
            }
    return info


# ------------------------------------------------------------------
# Type coercion (auto-detected from Django model field)
# ------------------------------------------------------------------


def _coerce(
    model_class: type[ClaimControlledModel], attr: str, value: object
) -> object:
    """Coerce a JSON claim value to the type expected by the model field."""
    if value is None or value == "":
        field = model_class._meta.get_field(attr)
        return None if field.null else ""

    field = model_class._meta.get_field(attr)

    if isinstance(
        field,
        models.IntegerField
        | models.SmallIntegerField
        | models.PositiveIntegerField
        | models.PositiveSmallIntegerField
        | models.BigIntegerField,
    ):
        try:
            return int(value)  # type: ignore[call-overload]
        except ValueError, TypeError:
            logger.warning("Cannot coerce %r to int for field %s", value, attr)
            return None if field.null else 0

    if isinstance(field, models.DecimalField):
        try:
            return Decimal(str(value))
        except InvalidOperation, ValueError, TypeError:
            logger.warning("Cannot coerce %r to Decimal for field %s", value, attr)
            return None if field.null else Decimal(0)

    if isinstance(field, models.BooleanField):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    return value


# ------------------------------------------------------------------
# Field defaults
# ------------------------------------------------------------------


def get_field_defaults(
    model_class: type[ClaimControlledModel],
    direct_fields: ClaimFieldMap,
) -> dict[str, Any]:
    """Compute reset values for direct fields by inspecting Django model metadata.

    The returned values are ``dict[str, Any]`` because Django field defaults
    are genuinely heterogeneous — any Python scalar, ``None``, or the return
    of an arbitrary callable.  Narrowing further would require per-field
    type variance that callers don't need.
    """
    # Values are Django field defaults — scalars, None, or callable output.
    defaults: dict[str, Any] = {}
    for attr in direct_fields.values():
        field = model_class._meta.get_field(attr)
        if hasattr(field, "default") and field.default is not models.NOT_PROVIDED:
            defaults[attr] = (
                field.default() if callable(field.default) else field.default
            )
        elif field.null or field.is_relation:
            # null fields default to None.  FK fields also default to None
            # as a safe transient value — Django's FK descriptor rejects ""
            # on assignment.  For non-nullable FKs, preserve_when_unclaimed
            # prevents this None from reaching the DB.
            defaults[attr] = None
        else:
            defaults[attr] = ""
    return defaults


def get_preserve_fields(
    model_class: type[ClaimControlledModel],
    direct_fields: ClaimFieldMap,
) -> set[str]:
    """Identify fields that must keep their existing value when no claim exists.

    These fields cannot safely be reset to a shared default during resolution:

    * **UNIQUE** — resetting multiple objects to ``""`` causes IntegrityError.
      Includes both ``unique=True`` fields and fields covered by Meta
      ``UniqueConstraint`` (e.g. ``UniqueConstraint(Lower("name"))``).
    * **Non-nullable FK** — Django's FK descriptor rejects ``""`` on assignment,
      and ``None`` violates the NOT NULL constraint.

    Returns a set of attribute names (values from *direct_fields*).
    """
    preserve: set[str] = set()
    constraint_unique = meta_unique_fields(model_class)
    for attr in direct_fields.values():
        field = model_class._meta.get_field(attr)
        is_unique = bool(getattr(field, "unique", False)) or attr in constraint_unique
        if is_unique or (field.many_to_one and not field.null):
            preserve.add(attr)
    return preserve


def get_nullable_unique_fields(
    model_class: type[ClaimControlledModel],
    direct_fields: ClaimFieldMap,
) -> list[str]:
    """Claim-controlled fields that are single-column ``unique=True`` AND nullable.

    These are the external-ID fields (``opdb_id``, ``wikidata_id``, …) that the
    bulk path de-conflicts by clearing the loser to ``None`` when two objects in
    a batch resolve to the same value.

    Deliberately tests **only** ``field.unique`` — NOT membership in a Meta
    ``UniqueConstraint``. De-confliction is destructive (it nulls the loser), so
    a field that is merely *part of a composite* unique key (e.g. ``Location``'s
    nullable ``parent`` inside ``(parent, slug)``) must never be treated as
    singly-unique here, or sibling rows would have their ``parent`` wrongly
    cleared. ``get_preserve_fields`` can safely use the broader predicate because
    preserving a value is always harmless; clearing one is not.

    Returns a sorted list so de-confliction order is deterministic.
    """
    fields: list[str] = []
    for attr in direct_fields.values():
        field = model_class._meta.get_field(attr)
        if getattr(field, "unique", False) and field.null:
            fields.append(attr)
    return sorted(fields)


def resolve_unique_conflicts(
    all_objs: Sequence[ClaimControlledModel],
    field_name: ClaimFieldName,
    model_class: type[ClaimControlledModel],
    pre_values: dict[int, Any] | None = None,
) -> None:
    """Detect and fix duplicate values for a UNIQUE field after resolution.

    Handles both nullable and non-nullable fields:

    * **Nullable** (e.g. ``opdb_id``): loser is cleared to ``None``.
    * **Non-nullable** (e.g. ``slug``): loser reverts to its pre-resolution
      value. Requires *pre_values* (``{pk: value}`` captured before resolution).
      When a preserver (unchanged value) conflicts with a changer (new value),
      the preserver wins — it's the rightful owner. Pre-resolution values are
      guaranteed unique by the DB constraint, so reverting never creates a
      secondary conflict.

    Mutates objects in place. The losing claim stays in the DB for manual
    inspection.
    """
    nullable = model_class._meta.get_field(field_name).null
    seen: dict[Any, ClaimControlledModel] = {}
    for obj in all_objs:
        value = getattr(obj, field_name)
        if not value:
            continue
        if value not in seen:
            seen[value] = obj
            continue

        owner = seen[value]
        if nullable:
            # Nullable: first encountered wins, loser clears to None.
            obj_name = getattr(obj, "name", f"<{type(obj).__name__}>")
            owner_name = getattr(owner, "name", f"<{type(owner).__name__}>")
            logger.warning(
                "Cannot resolve %s=%r onto '%s' (pk=%s): already owned by '%s' (pk=%s)",
                field_name,
                value,
                obj_name,
                obj.pk,
                owner_name,
                owner.pk,
            )
            setattr(obj, field_name, None)
        else:
            # Non-nullable: preserver wins over changer.
            if pre_values is None:
                raise ValueError(
                    "pre_values is required for non-nullable unique fields"
                )

            owner_changed = (
                getattr(owner, field_name) != pre_values[cast(int, owner.pk)]
            )
            obj_changed = value != pre_values[cast(int, obj.pk)]
            if owner_changed and not obj_changed:
                loser, winner = owner, obj
            else:
                loser, winner = obj, owner
            winner_name = getattr(winner, "name", f"<{type(winner).__name__}>")
            loser_name = getattr(loser, "name", f"<{type(loser).__name__}>")
            logger.warning(
                "%s conflict %r: keeping on '%s' (pk=%s), "
                "reverting '%s' (pk=%s) to previous value %r",
                field_name,
                getattr(winner, field_name),
                winner_name,
                winner.pk,
                loser_name,
                loser.pk,
                pre_values[cast(int, loser.pk)],
            )
            setattr(loser, field_name, pre_values[cast(int, loser.pk)])
            seen[getattr(winner, field_name)] = winner
