"""Theme and ThemeAlias models."""

from __future__ import annotations

from typing import ClassVar

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
    ScopePolicy,
    SingleSubject,
)

from .base import AliasModel, CatalogModel

__all__ = ["MachineModelTheme", "Theme", "ThemeAlias", "ThemeParent"]


class Theme(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """A thematic tag for pinball machines (e.g., Sports, Horror, Licensed).

    Supports a DAG hierarchy via the ``parents`` M2M (claim-controlled,
    materialized through ``ThemeParent``).  The MachineModel-Theme relationship
    is also materialized from relationship claims.
    """

    entity_type = "theme"
    entity_type_plural = "themes"
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset(
        {"machine_models", "children"}
    )
    aliases: models.Manager[ThemeAlias]
    children: models.Manager[Theme]

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])
    parents: models.ManyToManyField[Theme, ThemeParent] = models.ManyToManyField(
        "self",
        through="ThemeParent",
        through_fields=("from_theme", "to_theme"),
        symmetrical=False,
        related_name="children",
        blank=True,
        help_text="Parent themes in the hierarchy (materialized from relationship claims).",
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


class MachineModelTheme(ClaimThroughModel):
    """Through model for MachineModel ↔ Theme (materialized from relationship claims)."""

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="theme",
        subject=SingleSubject("machinemodel"),
        members=(MemberField("theme", identity="theme"),),
    )

    machinemodel = models.ForeignKey("MachineModel", on_delete=models.CASCADE)
    theme = models.ForeignKey(Theme, on_delete=models.PROTECT)

    class Meta:
        db_table = "catalog_machinemodel_themes"
        constraints = [
            models.UniqueConstraint(
                fields=["machinemodel", "theme"],
                name="catalog_machinemodeltheme_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.machinemodel} → {self.theme}"


class ThemeParent(ClaimThroughModel):
    """Through model for Theme's self-referential parents DAG (from claims).

    The child (``from_theme``) is the claim subject; the parent (``to_theme``)
    is the identity member — a plain ``SingleSubject`` shape, no dedicated
    self-parent variant. Pinned to the auto-M2M's table and columns so the
    promotion migration is state-only.
    """

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="theme_parent",
        subject=SingleSubject("from_theme"),
        members=(MemberField("to_theme", value_key="parent", identity="parent"),),
        ignore_conflicts=True,
        scope=ScopePolicy.FULL_TYPE,
    )

    from_theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="+")
    to_theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="+")

    class Meta:
        db_table = "catalog_theme_parents"
        unique_together = (("from_theme", "to_theme"),)

    def __str__(self) -> str:
        return f"{self.from_theme} → {self.to_theme}"


class ThemeAlias(AliasModel):
    """An alternate name for a Theme, used for matching/search."""

    alias_claim_field = "theme_alias"

    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="aliases")

    class Meta(AliasModel.Meta):
        constraints = [
            field_not_blank("value"),
            models.UniqueConstraint(
                Lower("value"),
                name="catalog_unique_theme_alias_lower",
            ),
        ]
