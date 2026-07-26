"""Manufacturer and CorporateEntity models."""

from __future__ import annotations

from collections.abc import Iterable

from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import (
    SluggedModel,
    TimeStampedModel,
    field_not_blank,
    nullable_id_not_empty,
    slug_lowercase,
    slug_not_blank,
    status_valid,
    unique_ci,
)
from apps.core.validators import validate_no_mojibake
from apps.core.wikilinks import WikilinkableModel
from apps.media.models import MediaSupportedModel

from .base import AliasModel, CatalogModel

__all__ = [
    "CorporateEntity",
    "CorporateEntityAlias",
    "Manufacturer",
    "ManufacturerAlias",
    "OperatingStatus",
]

YEAR_MIN, YEAR_MAX = 1800, 2100
EXTERNAL_ID_MIN = 1


class OperatingStatus(models.TextChoices):
    """Whether a corporate entity is still producing pinball.

    An explicit editorial signal that ``max(model.year)`` can't express — it
    distinguishes a defunct entity whose last title was recent from an active one
    currently on a multi-year gap (the MusicBrainz "ended" pattern).

    Member names are UPPERCASE, wire/DB/JSON values lowercase, matching the
    ``EntityStatus`` precedent. Every wire/claim/frontend value is the
    lowercase string; Python references the enum member.
    """

    ONGOING = "ongoing", "Ongoing"
    ENDED = "ended", "Ended"
    UNKNOWN = "unknown", "Unknown"

    @classmethod
    def rollup(cls, statuses: Iterable[str]) -> OperatingStatus:
        """Aggregate operating status for a parent over its corporate entities.

        Precedence ONGOING > UNKNOWN > ENDED: a manufacturer is ongoing if any
        incarnation is, ended only when every incarnation is known-ended, and
        unknown otherwise — including when it has no entities. Accepts wire
        strings or enum members (both normalize to the wire value).
        """
        values = {str(s) for s in statuses}
        if cls.ONGOING.value in values:
            return cls.ONGOING
        if values and values <= {cls.ENDED.value}:
            return cls.ENDED
        return cls.UNKNOWN


class Manufacturer(
    CatalogModel,
    SluggedModel,
    MediaSupportedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A pinball manufacturer as users know it — the name on the cabinet.

    Corporate incarnations are tracked separately in CorporateEntity.
    For example, "Gottlieb" is one Manufacturer with four CorporateEntity
    records spanning different ownership eras.
    """

    entity_type = "manufacturer"
    entity_type_plural = "manufacturers"
    MEDIA_CATEGORIES = ["logo", "other"]
    entities: models.Manager[CorporateEntity]

    link_sort_order = 30
    # Match on the manufacturer name and its direct aliases. Matching CorporateEntity
    # names is deliberately dropped — the listing's active-entity guard can't be
    # expressed as a flat field path; that nuance stays on the /manufacturers
    # listing.
    autocomplete_search_fields = ("name", "aliases__value")

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    opdb_manufacturer_id = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text="OPDB's manufacturer_id for this manufacturer.",
        validators=[MinValueValidator(EXTERNAL_ID_MIN)],
    )
    wikidata_id = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="Wikidata QID, e.g. Q180268",
        validators=[
            RegexValidator(
                r"^Q\d+$",
                message="Wikidata ID must be Q followed by digits (e.g. Q180268).",
            )
        ],
    )
    logo_url = models.URLField(null=True, blank=True)
    website = models.URLField(blank=True)

    # Free-form staging area for source-specific data that doesn't have a
    # dedicated column yet (e.g. fandom.description). Claims provide provenance
    # but no validation is applied. Promote keys to real fields when needed.
    extra_data = models.JSONField(default=dict, blank=True)

    entity_media = GenericRelation("media.EntityMedia")

    class Meta:
        ordering = ["name"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
            nullable_id_not_empty("wikidata_id"),
            models.CheckConstraint(
                condition=models.Q(opdb_manufacturer_id__isnull=True)
                | models.Q(opdb_manufacturer_id__gte=EXTERNAL_ID_MIN),
                name="catalog_manufacturer_opdb_manufacturer_id_min",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ManufacturerAlias(AliasModel):
    """An alternate name for a Manufacturer, used to match alternative spellings
    from external sources.
    """

    alias_claim_field = "manufacturer_alias"

    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.CASCADE, related_name="aliases"
    )

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                name="catalog_unique_manufacturer_alias_lower",
            ),
        ]


class CorporateEntity(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A specific corporate incarnation of a Manufacturer.

    IPDB tracks corporate entities (e.g., four separate entries for Gottlieb
    across its ownership eras). Each entity maps to one Manufacturer.
    """

    entity_type = "corporate-entity"
    entity_type_plural = "corporate-entities"

    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.PROTECT,
        related_name="entities",
    )
    slug = models.SlugField(max_length=300, unique=True)
    name = models.CharField(
        max_length=300,
        help_text='Full corporate name, e.g., "D. Gottlieb & Company"',
        validators=[validate_no_mojibake],
    )
    ipdb_manufacturer_id = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text="IPDB ManufacturerId for this corporate entity.",
        validators=[MinValueValidator(EXTERNAL_ID_MIN)],
    )
    year_start = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "DEAD FIELD — do not read or write. The asserted corporate founding "
            "year, retired because it answers the wrong question: a company can "
            "incorporate years before its first machine and linger years after "
            "its last. Use the derived year_of_first_model instead, as the page "
            "and export APIs do. Kept only so the cited claims behind it survive."
        ),
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    year_end = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "DEAD FIELD — do not read or write. The asserted year the corporate "
            "entity ceased operations; see year_start for why it was retired. Use "
            "the derived year_of_last_model instead, with operating_status for "
            "whether the entity has actually stopped. Kept only so the cited "
            "claims behind it survive."
        ),
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    operating_status = models.CharField(
        max_length=10,
        choices=OperatingStatus.choices,
        default=OperatingStatus.UNKNOWN,
        help_text="Whether this corporate entity is still producing pinball.",
    )

    class Meta:
        ordering = ["manufacturer", "year_start"]
        verbose_name = "corporate entity"
        verbose_name_plural = "corporate entities"
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            models.CheckConstraint(
                condition=models.Q(year_start__isnull=True)
                | models.Q(year_start__gte=YEAR_MIN, year_start__lte=YEAR_MAX),
                name="catalog_corporateentity_year_start_range",
            ),
            models.CheckConstraint(
                condition=models.Q(year_end__isnull=True)
                | models.Q(year_end__gte=YEAR_MIN, year_end__lte=YEAR_MAX),
                name="catalog_corporateentity_year_end_range",
            ),
            models.CheckConstraint(
                condition=models.Q(ipdb_manufacturer_id__isnull=True)
                | models.Q(ipdb_manufacturer_id__gte=EXTERNAL_ID_MIN),
                name="catalog_corporateentity_ipdb_manufacturer_id_min",
            ),
            # No ``OR IS NULL`` clause: operating_status is null=False, so every
            # row holds one of the choices (tighter than EntityStatus's nullable
            # status_valid() pattern).
            models.CheckConstraint(
                condition=models.Q(operating_status__in=OperatingStatus.values),
                name="catalog_corporateentity_operating_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(year_start__isnull=True)
                    | models.Q(year_end__isnull=True)
                    | models.Q(year_start__lte=models.F("year_end"))
                ),
                name="catalog_corporateentity_year_start_lte_year_end",
                violation_error_message="year_start must be <= year_end.",
                violation_error_code="cross_field",
            ),
        ]

    def __str__(self) -> str:
        if self.year_start:
            end = self.year_end or "present"
            return f"{self.name} ({self.year_start}-{end})"
        return self.name


class CorporateEntityAlias(AliasModel):
    """An alternate name for a CorporateEntity, used to match alternative spellings
    from external sources.
    """

    alias_claim_field = "corporate_entity_alias"

    corporate_entity = models.ForeignKey(
        CorporateEntity, on_delete=models.CASCADE, related_name="aliases"
    )

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                name="catalog_unique_corporate_entity_alias_lower",
            ),
        ]
