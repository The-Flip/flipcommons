"""Taxonomy lookup models — technology, display, cabinet, game format, etc."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

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
from apps.provenance.model_bases import (
    ClaimRelationshipSpec,
    ClaimThroughModel,
    MemberField,
    SingleSubject,
)

from .base import AliasModel, CatalogModel

if TYPE_CHECKING:
    from .machine_model import MachineModel
    from .person import Credit
    from .series import Series

__all__ = [
    "PRODUCED_SLUG",
    "Cabinet",
    "CreditRole",
    "DisplaySubtype",
    "DisplayType",
    "GameFormat",
    "MachineModelRewardType",
    "MachineModelTag",
    "ProductionStatus",
    "RewardType",
    "RewardTypeAlias",
    "Tag",
    "TechnologyGeneration",
    "TechnologySubgeneration",
]


class TechnologyGeneration(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A major technological era: Pure Mechanical, Electromechanical, Solid State."""

    entity_type = "technology-generation"
    entity_type_plural = "technology-generations"
    # Subgenerations are owned children (CASCADE FK) but are themselves lifecycle
    # entities, so soft-deleting a generation must cascade a status=deleted claim
    # to them — otherwise they survive active, orphaned under a deleted parent.
    # Because the cascade pulls each subgeneration into the plan, a subgeneration
    # still referenced by an active MachineModel (PROTECT) blocks the generation's
    # delete too, not only its own direct delete. Enforced by
    # check_soft_delete_policy (core.E114).
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset(
        {"subgenerations"}
    )

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class TechnologySubgeneration(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A subdivision within a TechnologyGeneration.

    e.g., Solid State → Discrete Logic, Integrated (MPU), PC-Based.
    """

    entity_type = "technology-subgeneration"
    entity_type_plural = "technology-subgenerations"
    technology_generation_id: int

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)
    technology_generation = models.ForeignKey(
        TechnologyGeneration,
        on_delete=models.CASCADE,
        related_name="subgenerations",
    )

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class DisplayType(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A display technology category: Score Reels, DMD, LCD etc."""

    entity_type = "display-type"
    entity_type_plural = "display-types"
    # Subtypes are owned children (CASCADE FK) but are themselves lifecycle
    # entities; soft-delete must cascade to them so they don't survive orphaned
    # under a deleted parent. A subtype still referenced by an active MachineModel
    # (PROTECT) blocks the type's delete too, not only its own. Enforced by
    # check_soft_delete_policy (core.E114).
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset({"subtypes"})

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class DisplaySubtype(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A subdivision within a DisplayType.

    e.g., LCD → Standard LCD, HD LCD.
    """

    entity_type = "display-subtype"
    entity_type_plural = "display-subtypes"
    display_type_id: int

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)
    display_type = models.ForeignKey(
        DisplayType,
        on_delete=models.CASCADE,
        related_name="subtypes",
    )

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class Cabinet(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """The form factor of the physical cabinet of the game, such as
    floor-standing, tabletop, cocktail etc."""

    entity_type = "cabinet"
    entity_type_plural = "cabinets"

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class GameFormat(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """The format of the game, such as pinball, bagatelle, pitch-and-bat etc"""

    entity_type = "game-format"
    entity_type_plural = "game-formats"

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class ProductionStatus(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """Status in regards to commercial production, such as whether it has been
    commercially produced, announced, or is a one-off never intended to be produced."""

    entity_type = "production-status"
    entity_type_plural = "production-statuses"

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        # Django's default pluralizer would yield "production statuss"; pin the
        # plural so the generated ``label_plural`` reads "Production Statuses".
        verbose_name_plural = "production statuses"
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


# The one ProductionStatus value that carries code-level meaning: it is
# suppressed on detail pages (a "produced" machine shows no status row). Used
# only as a *best-effort* comparison (never a ``.get``) — if the row is
# renamed, deleted or never created, the comparison simply stops matching and
# "produced" becomes visible: a cosmetic, recoverable degradation, never a
# crash. No value-guard machinery guards it.
#
# A frontend twin of this string lives in
# ``frontend/src/lib/entities/production-status.ts``; a rename must update both.
PRODUCED_SLUG = "produced"


class RewardType(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A pinball reward mechanism: replay, add-a-ball, free-play, etc.

    Reward types are the payoff mechanic for achieving a goal, distinct from
    gameplay features (the mechanisms used to earn that payoff).
    """

    entity_type = "reward-type"
    entity_type_plural = "reward-types"
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset({"machine_models"})

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class MachineModelRewardType(ClaimThroughModel):
    """Through model for MachineModel ↔ RewardType (materialized from relationship claims)."""

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="reward_type",
        subject=SingleSubject("machinemodel"),
        members=(
            # FK column squishes the model name; the claim value key keeps the
            # snake-case namespace.
            MemberField("rewardtype", value_key="reward_type", identity="reward_type"),
        ),
    )

    machinemodel = models.ForeignKey("MachineModel", on_delete=models.CASCADE)
    rewardtype = models.ForeignKey(RewardType, on_delete=models.PROTECT)

    class Meta:
        db_table = "catalog_machinemodel_reward_types"
        constraints = [
            models.UniqueConstraint(
                fields=["machinemodel", "rewardtype"],
                name="catalog_machinemodelrewardtype_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.machinemodel} → {self.rewardtype}"


class RewardTypeAlias(AliasModel):
    """An alternate name for a RewardType, used for matching/search."""

    alias_claim_field = "reward_type_alias"

    reward_type = models.ForeignKey(
        RewardType, on_delete=models.CASCADE, related_name="aliases"
    )

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                name="catalog_unique_reward_type_alias_lower",
            ),
        ]


class Tag(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A classification tag, such as Home Use, Prototype, Widebody etc.

    Linked to MachineModel via M2M relationship claims.
    """

    entity_type = "tag"
    entity_type_plural = "tags"
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset({"machine_models"})

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name


class MachineModelTag(ClaimThroughModel):
    """Through model for MachineModel ↔ Tag (materialized from relationship claims)."""

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="tag",
        subject=SingleSubject("machinemodel"),
        members=(MemberField("tag", identity="tag"),),
    )

    machinemodel = models.ForeignKey("MachineModel", on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.PROTECT)

    class Meta:
        db_table = "catalog_machinemodel_tags"
        constraints = [
            models.UniqueConstraint(
                fields=["machinemodel", "tag"],
                name="catalog_machinemodeltag_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.machinemodel} → {self.tag}"


class CreditRole(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A credit role category: Design, Art, Software, etc."""

    entity_type = "credit-role"
    entity_type_plural = "credit-roles"
    # Soft-delete is blocked by any active machine or series credited in this
    # role. Credit itself has no LifecycleStatusModel, so we expose two M2M
    # accessors through Credit and let the generic usage-blocker walker
    # (soft_delete._iter_usage_blockers) filter each via .active().
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset(
        {"machine_models", "series_credited"}
    )

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    display_order = models.PositiveSmallIntegerField(default=0)

    machine_models: models.ManyToManyField[MachineModel, Credit] = (
        models.ManyToManyField(
            "MachineModel",
            through="Credit",
            through_fields=("role", "model"),
            related_name="+",
        )
    )
    series_credited: models.ManyToManyField[Series, Credit] = models.ManyToManyField(
        "Series",
        through="Credit",
        through_fields=("role", "series"),
        related_name="+",
    )

    class Meta:
        ordering = ["display_order"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            unique_ci("name"),
        ]

    def __str__(self) -> str:
        return self.name
