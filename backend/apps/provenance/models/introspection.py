"""Introspection helpers for claim-controlled models."""

from __future__ import annotations

from django.db import models

from apps.core.types import ClaimFieldMap

from ..model_bases import ClaimControlledModel

__all__ = ["get_claim_fields"]


# Infrastructure fields exempt from claims on every model.
_CLAIMS_EXEMPT_NAMES = frozenset(
    {"id", "uuid", "created_at", "updated_at", "extra_data"}
)


def get_claim_fields(model_class: type[ClaimControlledModel]) -> ClaimFieldMap:
    """Discover claim-controlled fields by introspecting a Django model.

    Returns ``{field_name: field_name}`` for every concrete field that is
    claim-controlled.  Fields are excluded if they are:

    * primary keys
    * database-generated (``GeneratedField``) — derived, never user-input
    * in ``_CLAIMS_EXEMPT_NAMES`` (infrastructure fields)
    * listed in the model's ``claims_exempt`` class attribute
    * GenericForeignKey helper columns (``content_type``, ``object_id``)

    FK fields are included — the resolver handles slug lookup automatically.
    """
    per_model_exempt = model_class.claims_exempt
    fields: ClaimFieldMap = {}
    for f in model_class._meta.get_fields():
        if not isinstance(f, models.Field):
            continue
        if not getattr(f, "concrete", False):
            continue
        if f.primary_key:
            continue
        if isinstance(f, models.GeneratedField):
            continue
        if f.name in _CLAIMS_EXEMPT_NAMES:
            continue
        if f.name in per_model_exempt:
            continue
        # Skip GenericForeignKey helper columns (content_type_id, object_id).
        if f.name in ("content_type", "object_id"):
            continue
        fields[f.name] = f.name
    return fields
