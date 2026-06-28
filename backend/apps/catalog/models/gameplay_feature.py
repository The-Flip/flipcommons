"""GameplayFeature and GameplayFeatureAlias models."""

from __future__ import annotations

from typing import ClassVar

from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower

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
from apps.media.models import MediaSupportedModel

from .base import AliasModel, CatalogModel

__all__ = ["GameplayFeature", "GameplayFeatureAlias", "MachineModelGameplayFeature"]


class GameplayFeature(
    CatalogModel,
    SluggedModel,
    MediaSupportedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A gameplay mechanism: Flippers, Pop Bumpers, Ramps, Multiball, etc.

    Supports a DAG hierarchy via the ``parents`` M2M (claim-controlled).
    The MachineModel-GameplayFeature relationship is materialized from claims.
    """

    entity_type = "gameplay-feature"
    entity_type_plural = "gameplay-features"
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset(
        {"machine_models", "children"}
    )
    MEDIA_CATEGORIES = ["other"]
    aliases: models.Manager[GameplayFeatureAlias]
    children: models.Manager[GameplayFeature]

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    parents = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="children",
        blank=True,
        help_text="Parent features in the hierarchy (materialized from relationship claims).",
    )

    entity_media = GenericRelation("media.EntityMedia")

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


COUNT_MIN = 1


class MachineModelGameplayFeature(models.Model):
    """Through model for MachineModel ↔ GameplayFeature, carrying optional count."""

    machinemodel = models.ForeignKey("MachineModel", on_delete=models.CASCADE)
    gameplayfeature = models.ForeignKey(GameplayFeature, on_delete=models.PROTECT)
    count = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Quantity from source data, e.g. Flippers (2) → count=2.",
        validators=[MinValueValidator(COUNT_MIN)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["machinemodel", "gameplayfeature"],
                name="catalog_machinemodelgameplayfeature_unique_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(count__isnull=True) | models.Q(count__gte=COUNT_MIN),
                name="catalog_machinemodelgameplayfeature_count_min",
            ),
        ]

    def __str__(self) -> str:
        label = f"{self.machinemodel} → {self.gameplayfeature}"
        if self.count is not None:
            label += f" ({self.count})"
        return label


class GameplayFeatureAlias(AliasModel):
    """An alternate name for a GameplayFeature, used for matching/search."""

    alias_claim_field = "gameplay_feature_alias"

    feature = models.ForeignKey(
        GameplayFeature, on_delete=models.CASCADE, related_name="aliases"
    )

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                name="catalog_unique_gameplay_feature_alias_lower",
            ),
        ]
