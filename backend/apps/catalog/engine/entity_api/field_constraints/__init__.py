"""Read-side numeric field-constraint introspection over any ``ClaimControlledModel``.

The read sibling of the create form: model-driven min / max / step metadata
derived from each numeric claim field's declared validators, served by
``GET /field-constraints/{entity_type}`` and consumed by both the create and
edit forms. It lives in the engine (not the write app) because it is generic,
read-only field metadata — out of place in a write engine.
"""

from __future__ import annotations

from typing import cast

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models as db_models
from ninja import Schema

from apps.provenance.models import ClaimControlledModel, get_claim_fields

__all__ = ["FieldConstraintSchema", "get_field_constraints"]


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
