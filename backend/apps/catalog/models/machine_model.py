"""MachineModel and ModelAbbreviation models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar

from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import (
    SluggedModel,
    TimeStampedModel,
    active_status_q,
    field_not_blank,
    nullable_id_not_empty,
    slug_lowercase,
    slug_not_blank,
    status_valid,
)
from apps.core.validators import validate_no_mojibake
from apps.core.wikilinks import WikilinkableModel
from apps.media.models import MediaSupportedModel
from apps.provenance.model_bases import (
    ClaimRelationshipSpec,
    ClaimThroughModel,
    MemberField,
    SingleSubject,
)

from ._autocomplete import manufacturer_year_sublabel
from .base import CatalogModel

__all__ = ["MachineModel", "ModelAbbreviation"]

if TYPE_CHECKING:
    from .gameplay_feature import GameplayFeature, MachineModelGameplayFeature
    from .person import Credit
    from .taxonomy import (
        MachineModelRewardType,
        MachineModelTag,
        RewardType,
        Tag,
    )
    from .theme import MachineModelTheme, Theme

# Range constants — referenced by both field validators and Meta.constraints.
# Module-level so they're accessible inside class Meta (nested class scoping).
YEAR_MIN, YEAR_MAX = 1800, 2100
MONTH_MIN, MONTH_MAX = 1, 12
PLAYER_COUNT_MIN, PLAYER_COUNT_MAX = 1, 20
FLIPPER_COUNT_MIN, FLIPPER_COUNT_MAX = 0, 20
RATING_MIN, RATING_MAX = 0, 10
EXTERNAL_ID_MIN = 1


class MachineModel(
    CatalogModel,
    SluggedModel,
    MediaSupportedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A pinball machine title/design — the resolved/materialized view.

    Fields are derived from resolving claims. The resolution logic picks the
    winning claim per field (highest priority source, most recent if tied).

    The public entity_type is 'model' (not 'machinemodel'): Django's
    ``Model`` base class conflicts with the ideal name, so the class is
    ``MachineModel`` but the public-facing identifier drops the prefix.
    """

    entity_type = "model"
    entity_type_plural = "models"
    MEDIA_CATEGORIES = ["backglass", "playfield", "cabinet", "other"]
    abbreviations: models.Manager[ModelAbbreviation]
    credits: models.Manager[Credit]
    title_id: int
    technology_generation_id: int | None

    link_sort_order = 20
    # Reach the manufacturer for the autocomplete sublabel in one join (year is
    # a direct field). No queryset override needed — the engine applies this.
    autocomplete_select_related = ("corporate_entity__manufacturer",)

    # Identity
    name = models.CharField(max_length=300, validators=[validate_no_mojibake])
    slug = models.SlugField(max_length=300, unique=True)

    # Cross-reference IDs
    ipdb_id = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        verbose_name="IPDB ID",
        validators=[MinValueValidator(EXTERNAL_ID_MIN)],
        help_text="Internet Pinball Database numeric id for this machine.",
    )
    opdb_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        verbose_name="OPDB ID",
        validators=[validate_no_mojibake],
        help_text="Open Pinball Database id (e.g. 'GRBE5-MQK7e').",
    )
    pinside_id = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        verbose_name="Pinside ID",
        validators=[validate_no_mojibake],
        help_text="Pinside.com game id slug for this machine.",
    )

    # Hierarchy
    title = models.ForeignKey(
        "Title",
        on_delete=models.PROTECT,
        related_name="machine_models",
        help_text="Title this machine belongs to.",
    )
    variant_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="variants",
        null=True,
        blank=True,
        help_text="Parent machine model if this is a cosmetic/LE variant.",
    )
    converted_from = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="conversions",
        null=True,
        blank=True,
        help_text="Source machine if this is a conversion/retheme.",
    )
    remake_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="remakes",
        null=True,
        blank=True,
        help_text="Original model if this is a remake.",
    )
    bootleg_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="bootlegs",
        null=True,
        blank=True,
        help_text=(
            "Original machine this is an unauthorized copy (bootleg) of. "
            "Unlike remakes and conversions, may belong to a different Title."
        ),
    )

    # Core filterable fields
    corporate_entity = models.ForeignKey(
        "CorporateEntity",
        on_delete=models.PROTECT,
        related_name="models",
        null=True,
        blank=True,
        help_text="Specific corporate incarnation that produced this model.",
    )
    year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(MONTH_MIN), MaxValueValidator(MONTH_MAX)],
    )
    technology_generation = models.ForeignKey(
        "TechnologyGeneration",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Technology generation.",
    )
    technology_subgeneration = models.ForeignKey(
        "TechnologySubgeneration",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Technology subgeneration.",
    )
    display_type = models.ForeignKey(
        "DisplayType",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Display type.",
    )
    display_subtype = models.ForeignKey(
        "DisplaySubtype",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Display subtype.",
    )
    cabinet = models.ForeignKey(
        "Cabinet",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Form factor of the physical cabinet.",
    )
    game_format = models.ForeignKey(
        "GameFormat",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Game format.",
    )
    production_status = models.ForeignKey(
        "ProductionStatus",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Commercial production status.",
    )
    player_count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(PLAYER_COUNT_MIN),
            MaxValueValidator(PLAYER_COUNT_MAX),
        ],
    )
    themes: models.ManyToManyField[Theme, MachineModelTheme] = models.ManyToManyField(
        "Theme",
        through="MachineModelTheme",
        blank=True,
        related_name="machine_models",
        help_text="Resolved theme tags (materialized from relationship claims).",
    )
    gameplay_features: models.ManyToManyField[
        GameplayFeature, MachineModelGameplayFeature
    ] = models.ManyToManyField(
        "GameplayFeature",
        through="MachineModelGameplayFeature",
        blank=True,
        related_name="machine_models",
        help_text="Gameplay features (materialized from relationship claims).",
    )
    reward_types: models.ManyToManyField[RewardType, MachineModelRewardType] = (
        models.ManyToManyField(
            "RewardType",
            through="MachineModelRewardType",
            blank=True,
            related_name="machine_models",
            help_text="Reward types (materialized from relationship claims).",
        )
    )
    tags: models.ManyToManyField[Tag, MachineModelTag] = models.ManyToManyField(
        "Tag",
        through="MachineModelTag",
        blank=True,
        related_name="machine_models",
        help_text="Classification tags (materialized from relationship claims).",
    )
    production_quantity = models.CharField(
        max_length=100,
        blank=True,
        validators=[validate_no_mojibake],
        help_text="Number of units produced, as free text (e.g. '6,000' or 'unknown').",
    )
    system = models.ForeignKey(
        "System",
        on_delete=models.PROTECT,
        related_name="machine_models",
        null=True,
        blank=True,
        help_text="Hardware system.",
    )
    flipper_count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(FLIPPER_COUNT_MIN),
            MaxValueValidator(FLIPPER_COUNT_MAX),
        ],
    )

    # Ratings
    ipdb_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(RATING_MIN), MaxValueValidator(RATING_MAX)],
    )
    pinside_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(RATING_MIN), MaxValueValidator(RATING_MAX)],
    )

    # Free-form staging area for source-specific data that doesn't have a
    # dedicated column yet. Claims provide provenance but no validation is
    # applied. Promote keys to real fields when needed.
    extra_data = models.JSONField(default=dict, blank=True)

    # Reverse access to provenance claims for this model.
    entity_media = GenericRelation("media.EntityMedia")

    class Meta:
        verbose_name = "model"
        verbose_name_plural = "models"
        ordering = ["name"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            # Range constraints
            models.CheckConstraint(
                condition=models.Q(year__isnull=True)
                | models.Q(year__gte=YEAR_MIN, year__lte=YEAR_MAX),
                name="catalog_machinemodel_year_range",
            ),
            models.CheckConstraint(
                condition=models.Q(month__isnull=True)
                | models.Q(month__gte=MONTH_MIN, month__lte=MONTH_MAX),
                name="catalog_machinemodel_month_range",
            ),
            models.CheckConstraint(
                condition=models.Q(player_count__isnull=True)
                | models.Q(
                    player_count__gte=PLAYER_COUNT_MIN,
                    player_count__lte=PLAYER_COUNT_MAX,
                ),
                name="catalog_machinemodel_player_count_range",
            ),
            models.CheckConstraint(
                condition=models.Q(flipper_count__isnull=True)
                | models.Q(
                    flipper_count__gte=FLIPPER_COUNT_MIN,
                    flipper_count__lte=FLIPPER_COUNT_MAX,
                ),
                name="catalog_machinemodel_flipper_count_range",
            ),
            models.CheckConstraint(
                condition=models.Q(ipdb_rating__isnull=True)
                | models.Q(ipdb_rating__gte=RATING_MIN, ipdb_rating__lte=RATING_MAX),
                name="catalog_machinemodel_ipdb_rating_range",
            ),
            models.CheckConstraint(
                condition=models.Q(pinside_rating__isnull=True)
                | models.Q(
                    pinside_rating__gte=RATING_MIN,
                    pinside_rating__lte=RATING_MAX,
                ),
                name="catalog_machinemodel_pinside_rating_range",
            ),
            models.CheckConstraint(
                condition=models.Q(ipdb_id__isnull=True)
                | models.Q(ipdb_id__gte=EXTERNAL_ID_MIN),
                name="catalog_machinemodel_ipdb_id_min",
            ),
            # Nullable string IDs: NULL or non-empty
            nullable_id_not_empty("opdb_id"),
            nullable_id_not_empty("pinside_id"),
            # Cross-field: month requires year
            models.CheckConstraint(
                condition=models.Q(month__isnull=True) | models.Q(year__isnull=False),
                name="catalog_machinemodel_month_requires_year",
                violation_error_message="month requires year.",
                violation_error_code="cross_field",
            ),
            # Self-referential anti-cycle
            models.CheckConstraint(
                condition=models.Q(variant_of__isnull=True)
                | ~models.Q(variant_of=models.F("pk")),
                name="catalog_machinemodel_variant_of_not_self",
                violation_error_message="A machine model cannot be its own variant.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(converted_from__isnull=True)
                | ~models.Q(converted_from=models.F("pk")),
                name="catalog_machinemodel_converted_from_not_self",
                violation_error_message="A machine model cannot be converted from itself.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(remake_of__isnull=True)
                | ~models.Q(remake_of=models.F("pk")),
                name="catalog_machinemodel_remake_of_not_self",
                violation_error_message="A machine model cannot be a remake of itself.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(bootleg_of__isnull=True)
                | ~models.Q(bootleg_of=models.F("pk")),
                name="catalog_machinemodel_bootleg_of_not_self",
                violation_error_message="A machine model cannot be a bootleg of itself.",
                violation_error_code="cross_field",
            ),
        ]
        indexes = [
            models.Index(fields=["corporate_entity", "year"]),
            models.Index(fields=["technology_generation", "year"]),
            models.Index(fields=["display_type"]),
        ]

    @classmethod
    def first_model_candidates(cls) -> models.QuerySet[MachineModel]:
        """The "first model" rule, uncorrelated: a title's active, non-variant
        models, earliest-first by ``(year, name)``.

        Single source for that identity/order rule. Callers layer their own
        ``select_related`` / ``prefetch_related`` for their read shape, and
        :meth:`Title.first_model_subquery` correlates it with
        ``title=OuterRef("pk")``. Keeping it in one place stops the subquery, the
        title/card prefetches and the kiosk typeahead from drifting apart.
        """
        return (
            cls.objects.active()
            .filter(variant_of__isnull=True)
            .order_by("year", "name")
        )

    @classmethod
    def non_canonical_detail_slugs(cls) -> Iterable[str]:
        # Single-Model-Title rule (docs/SingleModelTitles.md): when a Title
        # has exactly one active MachineModel, the UI collapses to the Model
        # page but the Title slug is the canonical URL for the detail page,
        # so the Model's ``/models/<slug>`` is non-canonical. The Model's
        # ``/edit-history`` and ``/sources`` remain canonical (they list the
        # Model's history / sources, not the Title's), so we don't drop the
        # row from ``sitemap_queryset()`` — only its detail URL.
        return (
            cls.objects.active()
            .annotate(
                _sibling_count=models.Count(
                    "title__machine_models",
                    filter=active_status_q("title__machine_models"),
                )
            )
            .filter(_sibling_count=1)
            .values_list(cls.public_id_field, flat=True)
        )

    def autocomplete_sublabel(self) -> str | None:
        """Disambiguate same-named models with a "manufacturer · year" line.

        Reads the manufacturer through ``corporate_entity`` (pre-joined via
        ``autocomplete_select_related``) and the model's own ``year`` field.
        """
        manufacturer = (
            self.corporate_entity.manufacturer.name if self.corporate_entity else None
        )
        return manufacturer_year_sublabel(manufacturer, self.year)

    def __str__(self) -> str:
        parts = [self.name]
        if self.corporate_entity:
            parts.append(f"({self.corporate_entity})")
        if self.year:
            parts.append(f"[{self.year}]")
        return " ".join(parts)


class ModelAbbreviation(ClaimThroughModel):
    """A common abbreviation for a MachineModel, e.g. "TS4LE" for Toy Story 4 LE.

    Materialized from provenance claims; each abbreviation is individually
    tracked with source attribution.
    """

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="abbreviation",
        subject=SingleSubject("machine_model"),
        members=(MemberField("value", identity="value"),),
    )

    machine_model = models.ForeignKey(
        MachineModel, on_delete=models.CASCADE, related_name="abbreviations"
    )
    value = models.CharField(max_length=50)

    class Meta:
        ordering = ["value"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine_model", "value"],
                name="catalog_modelabbreviation_unique_model_value",
            ),
            field_not_blank("value"),
        ]

    def __str__(self) -> str:
        return self.value
