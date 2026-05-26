"""Title and TitleAbbreviation models."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Coalesce, Greatest

from apps.core.markdown import MarkdownField
from apps.core.models import (
    BoundedTextField,
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

from .base import CatalogModel

__all__ = ["Title", "TitleAbbreviation"]

EXTERNAL_ID_MIN = 1
TITLE_NEEDS_REVIEW_NOTES_MAX_LENGTH = 2_000

if TYPE_CHECKING:
    from .machine_model import MachineModel


class Title(
    CatalogModel,
    SluggedModel,
    TimeStampedModel,
    WikilinkableModel,
):
    """The canonical identity of a pinball game, independent of edition or variant.

    OPDB calls this a "group" in its JSON, but we use "Title" as it is the
    natural pinball-world term (e.g., "Medieval Madness" spans the 1997
    original, the 2015 remake, and LE/SE variants). All fields are resolved
    from claims, just like MachineModel and Manufacturer.
    """

    entity_type = "title"
    entity_type_plural = "titles"
    link_sort_order = 10
    abbreviations: models.Manager[TitleAbbreviation]
    franchise_id: int | None
    machine_models: models.Manager[MachineModel]
    series_id: int | None

    # A user-driven soft-delete of a Title cascades to its active MachineModels
    # (each gets a ``status=deleted`` claim in the same ChangeSet). The DB FK
    # from MachineModel.title is PROTECT, which blocks hard deletion; the
    # cascade here is an application-layer rule over resolved ``status``.
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset(
        {"machine_models"}
    )

    opdb_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        verbose_name="OPDB group ID",
        help_text='OPDB group ID (e.g., "G5pe4"). Null for titles without an OPDB group.',
        validators=[validate_no_mojibake],
    )
    name = models.CharField(max_length=300, validators=[validate_no_mojibake])
    slug = models.SlugField(max_length=300, unique=True)
    description = MarkdownField(blank=True)
    franchise = models.ForeignKey(
        "Franchise",
        on_delete=models.PROTECT,
        related_name="titles",
        null=True,
        blank=True,
    )
    series = models.ForeignKey(
        "Series",
        on_delete=models.PROTECT,
        related_name="titles",
        null=True,
        blank=True,
    )
    fandom_page_id = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text="Fandom wiki page ID for deep-linking.",
        validators=[MinValueValidator(EXTERNAL_ID_MIN)],
    )
    needs_review = models.BooleanField(
        default=False,
        help_text="Title was auto-generated and may need human review.",
    )
    needs_review_notes = BoundedTextField(
        max_length=TITLE_NEEDS_REVIEW_NOTES_MAX_LENGTH,
        blank=True,
        help_text="Context for reviewers about why this title needs attention.",
        validators=[validate_no_mojibake],
    )

    # Reverse access to provenance claims for this title.
    class Meta:
        ordering = ["name"]
        constraints = [
            slug_not_blank(),
            slug_lowercase(),
            status_valid(),
            field_not_blank("name"),
            nullable_id_not_empty("opdb_id"),
            models.CheckConstraint(
                condition=models.Q(fandom_page_id__isnull=True)
                | models.Q(fandom_page_id__gte=EXTERNAL_ID_MIN),
                name="catalog_title_fandom_page_id_min",
            ),
        ]

    @classmethod
    def sitemap_queryset(cls) -> models.QuerySet[Title]:
        # Title is the only catalog page whose primary content aggregates
        # other catalog entities (the Model list, plus — for single-Model
        # Titles — the collapsed Model's content). Bump ``lastmod`` whenever
        # any child Model changes.
        #
        # ``Max("machine_models__updated_at")`` intentionally includes
        # deleted Models: soft-deleting a Model shrinks the Title's Model
        # list, which IS a change to the Title's rendered content, so the
        # delete time should bump ``lastmod``.
        #
        # Built from ``cls.objects.active()`` rather than ``super()`` to
        # avoid a double-``annotate`` on ``_sitemap_lastmod`` (whose
        # last-wins behavior varies across Django versions). ``Coalesce``
        # falls back to ``updated_at`` when a Title has no MachineModels —
        # Postgres' ``GREATEST`` already ignores NULLs but the explicit
        # fallback keeps the expression portable.
        return (
            cls.objects.active()
            .annotate(
                _sitemap_lastmod=Greatest(
                    models.F("updated_at"),
                    Coalesce(
                        models.Max("machine_models__updated_at"),
                        models.F("updated_at"),
                    ),
                ),
            )
            .only(cls.public_id_field, "updated_at")
            .order_by(cls.public_id_field)
        )

    def __str__(self) -> str:
        return self.name


class TitleAbbreviation(TimeStampedModel):
    """A common abbreviation for a Title, e.g. "MM" for Medieval Madness.

    Materialized from provenance claims; each abbreviation is individually
    tracked with source attribution.
    """

    title = models.ForeignKey(
        Title, on_delete=models.CASCADE, related_name="abbreviations"
    )
    value = models.CharField(max_length=50)

    class Meta:
        ordering = ["value"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "value"],
                name="catalog_titleabbreviation_unique_title_value",
            ),
            field_not_blank("value"),
        ]

    def __str__(self) -> str:
        return self.value
