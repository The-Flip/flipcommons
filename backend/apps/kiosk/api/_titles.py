"""Shared "title → first-model manufacturer + year" derivation.

Both the public kiosk *display* page and the superuser *editor* config show each
title's manufacturer and year, derived live from the title's first non-variant
model. The rule (which model is "first", how its manufacturer/year are read)
lives here so the two endpoints can't drift — the editor must label a configured
row exactly as the display page labels it.
"""

from __future__ import annotations

from typing import NamedTuple

from django.db.models import Prefetch, QuerySet

from apps.catalog.api.schemas import EntityRef
from apps.catalog.models import MachineModel, Title


class FirstModelSummary(NamedTuple):
    """A title's first model and the manufacturer + year it inherits from it.

    ``model`` is the instance itself (the display page reads its media for a
    thumbnail); ``manufacturer``/``year`` are the derived label parts both
    endpoints render. All three are ``None`` when the title has no model.
    """

    model: MachineModel | None
    manufacturer: EntityRef | None
    year: int | None


def first_model_queryset() -> QuerySet[MachineModel]:
    """The "first model" rule as a queryset: earliest active non-variant model
    by ``(year, name)``, with its manufacturer joined. Wrap in a ``Prefetch``
    against ``…title__machine_models`` so :func:`first_model_summary` can read
    ``title.machine_models.all()`` without an N+1."""
    return (
        MachineModel.objects.active()
        .filter(variant_of__isnull=True)
        .select_related("corporate_entity__manufacturer")
        .order_by("year", "name")
    )


def first_model_prefetch(lookup: str) -> Prefetch[str, QuerySet[MachineModel], str]:
    """A ``Prefetch`` of :func:`first_model_queryset` at ``lookup`` (e.g.
    ``"items__title__machine_models"`` off a config, or
    ``"title__machine_models"`` off an item queryset)."""
    return Prefetch(lookup, queryset=first_model_queryset())


def first_model_summary(title: Title) -> FirstModelSummary:
    """Manufacturer + year from ``title``'s first model.

    Requires ``title.machine_models`` to be prefetched via
    :func:`first_model_prefetch`; reads the first prefetched row.
    """
    first = next(iter(title.machine_models.all()), None)
    if first is None:
        return FirstModelSummary(None, None, None)
    mfr = (
        first.corporate_entity.manufacturer
        if first.corporate_entity and first.corporate_entity.manufacturer
        else None
    )
    manufacturer = (
        EntityRef(name=mfr.name, public_id=mfr.public_id) if mfr is not None else None
    )
    return FirstModelSummary(first, manufacturer, first.year)
