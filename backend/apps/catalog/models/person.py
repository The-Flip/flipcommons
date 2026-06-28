"""Person and Credit models."""

from __future__ import annotations

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
)
from apps.core.validators import validate_no_mojibake
from apps.core.wikilinks import WikilinkableModel
from apps.media.models import MediaSupportedModel

from .base import AliasModel, CatalogModel

__all__ = ["Credit", "Person", "PersonAlias"]

YEAR_MIN, YEAR_MAX = 1800, 2100
MONTH_MIN, MONTH_MAX = 1, 12
DAY_MIN, DAY_MAX = 1, 31


class Person(
    CatalogModel,
    SluggedModel,
    MediaSupportedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A person involved in pinball machine design (designer, artist, etc.)."""

    entity_type = "person"
    entity_type_plural = "people"
    MEDIA_CATEGORIES = ["portrait", "other"]
    aliases: models.Manager[PersonAlias]
    credits: models.Manager[Credit]

    link_sort_order = 40

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])

    # Wikidata cross-reference — direct field, not a claim
    wikidata_id = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        verbose_name="Wikidata ID",
        help_text='Wikidata QID, e.g., "Q312897"',
        validators=[
            RegexValidator(
                r"^Q\d+$",
                message="Wikidata ID must be Q followed by digits (e.g. Q312897).",
            )
        ],
    )

    # Birth / death dates — claimed fields, resolved from provenance
    birth_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    birth_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(MONTH_MIN), MaxValueValidator(MONTH_MAX)],
    )
    birth_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(DAY_MIN), MaxValueValidator(DAY_MAX)],
    )
    death_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    death_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(MONTH_MIN), MaxValueValidator(MONTH_MAX)],
    )
    death_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(DAY_MIN), MaxValueValidator(DAY_MAX)],
    )

    # Biography context — claimed fields, resolved from provenance
    birth_place = models.CharField(
        max_length=200, null=True, blank=True, validators=[validate_no_mojibake]
    )
    nationality = models.CharField(
        max_length=200, null=True, blank=True, validators=[validate_no_mojibake]
    )
    photo_url = models.URLField(null=True, blank=True)

    # Free-form staging area for source-specific data that doesn't have a
    # dedicated column yet (e.g. fandom.bio). Claims provide provenance
    # but no validation is applied. Promote keys to real fields when needed.
    extra_data = models.JSONField(default=dict, blank=True)

    entity_media = GenericRelation("media.EntityMedia")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "people"
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            nullable_id_not_empty("wikidata_id"),
            # Range constraints
            models.CheckConstraint(
                condition=models.Q(birth_year__isnull=True)
                | models.Q(birth_year__gte=YEAR_MIN, birth_year__lte=YEAR_MAX),
                name="catalog_person_birth_year_range",
            ),
            models.CheckConstraint(
                condition=models.Q(death_year__isnull=True)
                | models.Q(death_year__gte=YEAR_MIN, death_year__lte=YEAR_MAX),
                name="catalog_person_death_year_range",
            ),
            models.CheckConstraint(
                condition=models.Q(birth_month__isnull=True)
                | models.Q(birth_month__gte=MONTH_MIN, birth_month__lte=MONTH_MAX),
                name="catalog_person_birth_month_range",
            ),
            models.CheckConstraint(
                condition=models.Q(death_month__isnull=True)
                | models.Q(death_month__gte=MONTH_MIN, death_month__lte=MONTH_MAX),
                name="catalog_person_death_month_range",
            ),
            models.CheckConstraint(
                condition=models.Q(birth_day__isnull=True)
                | models.Q(birth_day__gte=DAY_MIN, birth_day__lte=DAY_MAX),
                name="catalog_person_birth_day_range",
            ),
            models.CheckConstraint(
                condition=models.Q(death_day__isnull=True)
                | models.Q(death_day__gte=DAY_MIN, death_day__lte=DAY_MAX),
                name="catalog_person_death_day_range",
            ),
            # Cross-field: birth_year <= death_year
            models.CheckConstraint(
                condition=(
                    models.Q(birth_year__isnull=True)
                    | models.Q(death_year__isnull=True)
                    | models.Q(birth_year__lte=models.F("death_year"))
                ),
                name="catalog_person_birth_year_lte_death_year",
                violation_error_message="birth_year must be <= death_year.",
                violation_error_code="cross_field",
            ),
            # Cross-field: date component chains
            models.CheckConstraint(
                condition=models.Q(birth_month__isnull=True)
                | models.Q(birth_year__isnull=False),
                name="catalog_person_birth_month_requires_birth_year",
                violation_error_message="birth_month requires birth_year.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(birth_day__isnull=True)
                | models.Q(birth_month__isnull=False),
                name="catalog_person_birth_day_requires_birth_month",
                violation_error_message="birth_day requires birth_month.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(death_month__isnull=True)
                | models.Q(death_year__isnull=False),
                name="catalog_person_death_month_requires_death_year",
                violation_error_message="death_month requires death_year.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(death_day__isnull=True)
                | models.Q(death_month__isnull=False),
                name="catalog_person_death_day_requires_death_month",
                violation_error_message="death_day requires death_month.",
                violation_error_code="cross_field",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class PersonAlias(AliasModel):
    """An alternate name for a Person, used to match alternative spellings from
    external sources (e.g. "Keith Johnson" → "Keith P. Johnson").
    """

    alias_claim_field = "person_alias"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="aliases")

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                name="catalog_unique_person_alias_lower",
            ),
        ]


class Credit(models.Model):
    """Links a person to a machine model or series with a specific role."""

    model_id: int | None
    series_id: int | None
    person_id: int
    role_id: int

    model = models.ForeignKey(
        "MachineModel",
        on_delete=models.CASCADE,
        related_name="credits",
        null=True,
        blank=True,
    )
    series = models.ForeignKey(
        "Series",
        on_delete=models.CASCADE,
        related_name="credits",
        null=True,
        blank=True,
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    role = models.ForeignKey(
        "CreditRole",
        on_delete=models.PROTECT,
        related_name="credits",
    )

    class Meta:
        ordering = ["role__display_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["model", "person", "role"],
                name="catalog_unique_credit_per_model_person_role",
                condition=models.Q(model__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["series", "person", "role"],
                name="catalog_unique_credit_per_series_person_role",
                condition=models.Q(series__isnull=False),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(model__isnull=False, series__isnull=True)
                    | models.Q(model__isnull=True, series__isnull=False)
                ),
                name="catalog_credit_model_xor_series",
            ),
        ]

    def __str__(self) -> str:
        if self.model is not None:
            target = self.model.name
        elif self.series is not None:
            target = self.series.name
        else:
            target = "<unbound>"
        return f"{self.person.name} — {self.role.name} on {target}"
