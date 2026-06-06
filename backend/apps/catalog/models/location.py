"""Location, LocationAlias, and CorporateEntityLocation models."""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.db.models.functions import Lower

from apps.core.models import (
    TimeStampedModel,
    field_lowercase,
    field_not_blank,
    status_valid,
)
from apps.core.validators import validate_no_mojibake

from .base import AliasModel, CatalogModel
from .manufacturer import CorporateEntity

__all__ = [
    "CorporateEntityLocation",
    "Location",
    "LocationAlias",
]


class Location(CatalogModel, TimeStampedModel):
    """A canonical geographic location at any level of the hierarchy.

    The hierarchy is self-referential: a city's parent is its subdivision,
    a subdivision's parent is its country, etc.  ``location_path`` encodes
    the full ancestry (e.g., ``"usa/il/chicago"``) and is globally unique.
    ``slug`` is the last path segment only and is NOT globally unique.

    All display fields (name, location_type, code, description, divisions)
    are claim-controlled — pindata is the authoritative source.
    """

    entity_type: ClassVar[str] = "location"
    entity_type_plural: ClassVar[str] = "locations"
    # Location's slug is non-unique (only unique within parent); the
    # globally-unique URL identity lives on ``location_path``.
    public_id_field: ClassVar[str] = "location_path"
    # The user types ``slug`` in the create form; the server builds
    # ``location_path`` from ``parent.location_path + slug``. Surface
    # collision errors keyed under ``slug`` so the form binds them.
    public_id_form_field: ClassVar[str] = "slug"
    # Location is intentionally absent from the wikilink picker: it does not
    # inherit ``WikilinkableModel``. Existing ``[[location:...]]`` markdown
    # still renders — only authoring through the picker is gated.

    claims_exempt: ClassVar[frozenset[str]] = frozenset({"location_path"})
    claim_fk_lookups: ClassVar[dict[str, str]] = {"parent": "location_path"}
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset(
        {"corporate_entities"}
    )

    # system-derived from ``parent.location_path + "/" + slug`` — the
    # underlying claims live on ``slug`` and ``parent``, so this field is
    # claims_exempt to avoid two sources of truth for the same fact.
    location_path = models.CharField(max_length=500, unique=True)
    slug = models.SlugField(max_length=200)  # claim-controlled
    name = models.CharField(
        max_length=300, validators=[validate_no_mojibake]
    )  # claim-controlled
    location_type = models.CharField(
        max_length=50, blank=True, validators=[validate_no_mojibake]
    )  # claim-controlled
    code = models.CharField(
        max_length=20, blank=True, validators=[validate_no_mojibake]
    )  # claim-controlled
    short_name = models.CharField(
        max_length=100,
        blank=True,
        validators=[validate_no_mojibake],
        help_text="Compact display form of the name, e.g. 'USA' for 'United States of America'.",
    )  # claim-controlled; e.g. "USA", "UK"
    # claim-controlled; list of level-type labels for countries only
    # e.g. ["state", "city"] or ["region", "department", "city"]
    divisions = models.JSONField(null=True, blank=True)
    # claim-controlled
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    # Reverse accessor intentionally suppressed (``related_name="+"``);
    # CorporateEntity already reaches Location through ``CorporateEntityLocation``
    # via ``corporate_entity_locations``. The forward side gives Location's
    # soft-delete walker a ``location.corporate_entities.active()`` accessor
    # for the ``soft_delete_usage_blockers`` entry above.
    corporate_entities: models.ManyToManyField[
        CorporateEntity, CorporateEntityLocation
    ] = models.ManyToManyField(
        "catalog.CorporateEntity",
        through="CorporateEntityLocation",
        related_name="+",
    )

    class Meta:
        ordering = ["location_path"]
        constraints = [
            field_not_blank("location_path"),
            field_not_blank("slug"),
            field_not_blank("name"),
            field_lowercase("slug"),
            field_lowercase("location_path"),
            status_valid(),
            models.CheckConstraint(
                condition=models.Q(parent__isnull=True)
                | ~models.Q(parent=models.F("pk")),
                name="catalog_location_parent_not_self",
                violation_error_message="A location cannot be its own parent.",
                violation_error_code="cross_field",
            ),
            models.UniqueConstraint(
                fields=["parent", "slug"],
                condition=models.Q(parent__isnull=False),
                name="catalog_location_unique_slug_per_parent",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(parent__isnull=True),
                name="catalog_location_unique_slug_at_root",
            ),
            models.UniqueConstraint(
                "parent",
                Lower("name"),
                condition=models.Q(parent__isnull=False),
                name="catalog_location_unique_name_per_parent",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(parent__isnull=True),
                name="catalog_location_unique_name_at_root",
            ),
        ]

    def __str__(self) -> str:
        return self.name or self.location_path


class LocationAlias(AliasModel, TimeStampedModel):
    """An alternate name for a Location used to match external source strings.

    Intentional mojibake aliases exist to match incorrectly encoded strings
    from IPDB/OPDB (e.g., ``"Vienne-le-Ch\ufffdteau"``).
    """

    alias_claim_field = "location_alias"

    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="aliases"
    )

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                "location",
                name="catalog_unique_location_alias_per_location",
            ),
        ]


class CorporateEntityLocation(TimeStampedModel):
    """Associates a CorporateEntity with a canonical Location.

    One-to-many: a CE can have multiple locations.
    ``location`` points to the most specific known level (city, subdivision,
    or country).  The full hierarchy is accessible via ``location.parent``.

    Existence is controlled by ``"location"`` relationship claims on
    CorporateEntity — do not create or delete rows directly.
    """

    corporate_entity_id: int
    location_id: int
    corporate_entity = models.ForeignKey(
        "catalog.CorporateEntity",
        on_delete=models.CASCADE,
        related_name="locations",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="corporate_entity_locations",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["corporate_entity", "location"],
                name="catalog_corporateentitylocation_unique_pair",
            ),
        ]
        verbose_name = "corporate entity location"
        verbose_name_plural = "corporate entity locations"

    def __str__(self) -> str:
        return f"{self.corporate_entity} → {self.location}"
