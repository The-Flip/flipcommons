"""System model."""

from __future__ import annotations

from django.db import models

from apps.core.models import (
    SluggedModel,
    TimeStampedModel,
    field_not_blank,
    slug_lowercase,
    slug_not_blank,
    status_valid,
    unique_ci,
)
from apps.core.validators import validate_no_mojibake
from apps.core.wikilinks import WikilinkableModel

from .base import CatalogModel

__all__ = ["System", "SystemMpuString"]


class System(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """An electronic hardware generation for pinball machines.

    e.g. WPC-95, System 6, SAM System, SPIKE.
    MachineModel.system FK is resolved from 'system' slug claims.
    """

    entity_type = "system"
    entity_type_plural = "systems"

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    manufacturer = models.ForeignKey(
        "Manufacturer",
        on_delete=models.PROTECT,
        related_name="systems",
    )
    technology_subgeneration = models.ForeignKey(
        "TechnologySubgeneration",
        on_delete=models.PROTECT,
        related_name="systems",
        null=True,
        blank=True,
        help_text="Technology subgeneration this system belongs to.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class SystemMpuString(TimeStampedModel):
    """An MPU board identifier string used to match machines to a System.

    e.g., "Stern SPIKE System", "Williams WPC-95".
    """

    system_id: int
    system = models.ForeignKey(
        System, on_delete=models.CASCADE, related_name="mpu_strings"
    )
    value = models.CharField(max_length=200)

    class Meta:
        ordering = ["value"]
        constraints = [
            models.UniqueConstraint(
                fields=["value"],
                name="catalog_unique_system_mpu_string",
            ),
            field_not_blank("value"),
        ]

    def __str__(self) -> str:
        return self.value
