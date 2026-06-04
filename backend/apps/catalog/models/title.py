"""Title and TitleAbbreviation models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import OuterRef, Subquery
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce, Greatest

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

from ._autocomplete import manufacturer_year_sublabel
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
    # Match on the title name and its abbreviations (Title has no alias
    # relation — ``abbreviations`` are its only alternate names). A title
    # typeahead matches title text, not its maker, so manufacturer is not a
    # search field.
    autocomplete_search_fields = ("name", "abbreviations__value")
    # Set by ``autocomplete_annotations`` (Subquery annotations); read by
    # ``autocomplete_sublabel``. Absent on instances fetched any other way.
    autocomplete_mfr_name: str | None
    autocomplete_year: int | None
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
    def lastmod_expression(cls) -> Combinable:
        # Title is the only catalog page whose primary content aggregates
        # other catalog entities (the Model list, plus — for single-Model
        # Titles — the collapsed Model's content). Bump ``lastmod`` whenever
        # any child Model changes — both in the sitemap's ``<lastmod>`` and in
        # the detail response's ``last_modified`` (both annotate via this one
        # expression, so they can't disagree).
        #
        # ``Max("machine_models__updated_at")`` intentionally includes
        # deleted Models: soft-deleting a Model shrinks the Title's Model
        # list, which IS a change to the Title's rendered content, so the
        # delete time should bump ``lastmod``. ``Coalesce`` falls back to
        # ``updated_at`` when a Title has no MachineModels — Postgres'
        # ``GREATEST`` already ignores NULLs but the explicit fallback keeps
        # the expression portable.
        return Greatest(
            models.F("updated_at"),
            Coalesce(
                models.Max("machine_models__updated_at"),
                models.F("updated_at"),
            ),
        )

    @classmethod
    def first_model_subquery(cls) -> models.QuerySet[MachineModel]:
        """The title's "first model" as a correlated subquery for annotations.

        The earliest non-variant active :class:`MachineModel` by ``(year,
        name)`` — the model whose manufacturer and year stand in for the title's
        own. Correlates on ``OuterRef("pk")``, so it's only valid inside a
        ``Subquery`` / ``annotate()`` over a ``Title`` queryset; the autocomplete
        sublabel and ``_title_facets`` both read from it.

        Canonical for the *subquery/annotation* uses only. The same
        ``variant_of__isnull=True`` + ``order_by("year", "name")`` rule is also
        expressed by the card/detail read paths (``_title_models_prefetch`` /
        ``_card_models_prefetch`` in ``api/titles.py``) via ``Prefetch``, which
        can't correlate and so restate it inline — a change to the rule must
        touch those too.
        """
        from .machine_model import MachineModel

        return (
            MachineModel.objects.filter(title=OuterRef("pk"), variant_of__isnull=True)
            .active()
            .order_by("year", "name")
        )

    @classmethod
    def autocomplete_annotations(cls) -> Mapping[str, Combinable]:
        """First-model manufacturer + year, so :meth:`autocomplete_sublabel`
        reads them without an N+1 (see :meth:`first_model_subquery` for the
        "first model" rule). The engine annotates these onto the queryset."""
        first_model = cls.first_model_subquery()
        return {
            "autocomplete_mfr_name": Subquery(
                first_model.values("corporate_entity__manufacturer__name")[:1]
            ),
            "autocomplete_year": Subquery(first_model.values("year")[:1]),
        }

    def autocomplete_sublabel(self) -> str | None:
        """Disambiguate same-named titles with a "manufacturer · year" line,
        read from the annotations :meth:`autocomplete_annotations` adds. Raises if
        called on an instance fetched any other way — that's a wiring error
        (the engine is the only intended caller), not a None to swallow."""
        return manufacturer_year_sublabel(
            self.autocomplete_mfr_name, self.autocomplete_year
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
