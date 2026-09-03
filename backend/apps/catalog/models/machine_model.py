"""MachineModel and ModelAbbreviation models."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum, auto
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Coalesce

from apps.core.models import (
    SluggedModel,
    TimeStampedModel,
    field_not_blank,
    nullable_id_not_empty,
    self_fk_not_self,
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
from .model_relationship import (
    SUBORDINATING_RELATIONSHIP_TYPES,
    ModelRelationship,
)

__all__ = ["MachineModel", "ModelAbbreviation", "SelfFkRole"]

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

# The "first model" ordering
_FIRST_MODEL_ORDER: tuple[str, ...] = ("_is_subordinate_copy", "year", "name")


class SelfFkRole(Enum):
    """What a ``MachineModel`` self-reference means to a reader.

    The schema can't tell the roles apart, so every self-FK must be classified
    in :attr:`MachineModel.self_fk_roles` and the edge vocabulary refuses to
    build otherwise — a new self-reference can't reach the published API just
    by existing.
    """

    LINEAGE = auto()
    """Product-facing: a relationship people filter and browse by, so the field
    becomes a public ``edge=`` filter key and a facet entry."""

    ADMINISTRATIVE = auto()
    """Bookkeeping: a merge target, a supersession pointer. Real data, but not
    a way anyone asks to see the catalog, so it stays out of the vocabulary."""


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

    # Literal, not bare str — see Title.entity_type.
    entity_type: ClassVar[Literal["model"]] = "model"
    entity_type_plural = "models"
    # A model targeted by another *active* model's relationship edge can't be
    # soft-deleted: the edge row itself has no lifecycle (so the PROTECT pass
    # skips it), but the owning source model would display a link to a 404.
    # The blocker walks through the edge to that source model — the same
    # channel Tag uses for its member models.
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset(
        {"inbound_relationship_sources"}
    )
    MEDIA_CATEGORIES = ["backglass", "playfield", "cabinet", "other"]
    abbreviations: models.Manager[ModelAbbreviation]
    credits: models.Manager[Credit]
    title_id: int
    technology_generation_id: int | None
    export_edition_of_id: int | None

    link_sort_order = 20
    # Reach the manufacturer for the autocomplete sublabel in one join (year is
    # a direct field). No queryset override needed — the engine applies this.
    autocomplete_select_related = ("corporate_entity__manufacturer",)
    # Provenance relationship labels use the same joins, but a deliberately
    # tighter one-line presentation than ``__str__`` (which names the full
    # corporate entity for admin/debug contexts).
    claim_display_select_related = autocomplete_select_related

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
    manufacturer_model_identifier = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Manufacturer Model ID",
        validators=[validate_no_mojibake],
        help_text="The manufacturer's own identifier for this model.",
    )

    # Hierarchy
    title = models.ForeignKey(
        "Title",
        on_delete=models.PROTECT,
        related_name="machine_models",
        help_text="Title this machine belongs to.",
    )
    # Every self-FK below must be classified — see SelfFkRole.
    self_fk_roles: ClassVar[Mapping[str, SelfFkRole]] = {
        "variant_of": SelfFkRole.LINEAGE,
        "remake_of": SelfFkRole.LINEAGE,
        "export_edition_of": SelfFkRole.LINEAGE,
    }
    # variant_of only: a variant is the same gameplay in different dress, so a
    # variant-of-a-variant asserts a dress of a dress — and the Title collapse
    # rule reads the shape directly (``first_model_candidates`` filters
    # ``variant_of__isnull=True``), so a chain moves a Title's representative
    # model and its page. ``remake_of`` legitimately chains across eras, and
    # ``export_edition_of`` is 1:1 with a domestic original.
    flat_self_fks: ClassVar[frozenset[str]] = frozenset({"variant_of"})
    variant_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="variants",
        null=True,
        blank=True,
        help_text="Parent machine model if this is a cosmetic/LE variant.",
    )
    remake_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="remakes",
        null=True,
        blank=True,
        help_text="Original model if this is a remake.",
    )
    # Singular by design: a model is the export edition of at
    # most one other model, and licensing doesn't apply (an unauthorized
    # "export" is a copy) — so this is a scalar lineage FK like variant_of /
    # remake_of, not a ModelRelationship edge type. When the domestic
    # original is unknown, this stays null and the export fact lives in
    # ModelExportMarket rows alone.
    export_edition_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="export_editions",
        null=True,
        blank=True,
        help_text="Domestic original if this model was built for an export market.",
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
    # Dates. Production date is physical assembly / factory rollout; project
    # date is the earlier milestone when the design was finalized or released
    # to production in the manufacturer's internal records. The generated
    # ``year``/``month`` pair below is what display, sorting, filtering and
    # aggregation read: production date when present, else project date.
    production_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    production_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(MONTH_MIN), MaxValueValidator(MONTH_MAX)],
    )
    project_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    project_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(MONTH_MIN), MaxValueValidator(MONTH_MAX)],
    )
    # The month pairs with whichever date supplied the year — a plain
    # per-column coalesce could stitch production's year to project's month.
    year = models.GeneratedField(
        expression=Coalesce("production_year", "project_year"),
        output_field=models.PositiveSmallIntegerField(),
        db_persist=True,
    )
    month = models.GeneratedField(
        expression=models.Case(
            models.When(
                production_year__isnull=False, then=models.F("production_month")
            ),
            default=models.F("project_month"),
        ),
        output_field=models.PositiveSmallIntegerField(),
        db_persist=True,
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
    # applied. Promote keys to real fields when used by the actual product.
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
                condition=models.Q(production_year__isnull=True)
                | models.Q(
                    production_year__gte=YEAR_MIN, production_year__lte=YEAR_MAX
                ),
                name="catalog_machinemodel_production_year_range",
            ),
            models.CheckConstraint(
                condition=models.Q(production_month__isnull=True)
                | models.Q(
                    production_month__gte=MONTH_MIN, production_month__lte=MONTH_MAX
                ),
                name="catalog_machinemodel_production_month_range",
            ),
            models.CheckConstraint(
                condition=models.Q(project_year__isnull=True)
                | models.Q(project_year__gte=YEAR_MIN, project_year__lte=YEAR_MAX),
                name="catalog_machinemodel_project_year_range",
            ),
            models.CheckConstraint(
                condition=models.Q(project_month__isnull=True)
                | models.Q(project_month__gte=MONTH_MIN, project_month__lte=MONTH_MAX),
                name="catalog_machinemodel_project_month_range",
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
            nullable_id_not_empty("manufacturer_model_identifier"),
            # Cross-field: month requires year
            models.CheckConstraint(
                condition=models.Q(production_month__isnull=True)
                | models.Q(production_year__isnull=False),
                name="catalog_machinemodel_production_month_requires_year",
                violation_error_message="production_month requires production_year.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(project_month__isnull=True)
                | models.Q(project_year__isnull=False),
                name="catalog_machinemodel_project_month_requires_year",
                violation_error_message="project_month requires project_year.",
                violation_error_code="cross_field",
            ),
            # Cross-field: project date cannot be after production date. A
            # null month gets the benefit of the doubt — project "1994" vs
            # production "1994-03" is allowed.
            models.CheckConstraint(
                condition=models.Q(project_year__isnull=True)
                | models.Q(production_year__isnull=True)
                | models.Q(project_year__lt=models.F("production_year"))
                | (
                    models.Q(project_year=models.F("production_year"))
                    & (
                        models.Q(project_month__isnull=True)
                        | models.Q(production_month__isnull=True)
                        | models.Q(project_month__lte=models.F("production_month"))
                    )
                ),
                name="catalog_machinemodel_project_lte_production",
                violation_error_message="project date cannot be after production date.",
                violation_error_code="cross_field",
            ),
            # One per self-FK — test_self_fk_constraints enforces the set.
            self_fk_not_self(
                "variant_of",
                message="A machine model cannot be its own variant.",
            ),
            self_fk_not_self(
                "remake_of",
                message="A machine model cannot be a remake of itself.",
            ),
            self_fk_not_self(
                "export_edition_of",
                message="A machine model cannot be an export edition of itself.",
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
        models, ordered so its representative (the first row) is an original —
        subordinate models sort last, then earliest-first by ``(year, name)``.

        Variants (cosmetic/LE) collapse out entirely. Subordinate models stay in
        the list but sort after every original, so ``.first()`` / ``[:1]`` never
        picks one over the model it derives from — while a Title whose *only*
        model is subordinate still surfaces it. Subordinate means a
        subordinating ``ModelRelationship`` edge exists (the Big Ben rule: the
        Williams original heads the Title, not its Segasa licensed build) —
        today a copy or a re-theme, where the source game outranks the
        derivative sharing its Title; conversions and kits are originals in
        their own right and don't subordinate. ``export_edition_of``
        subordinates the same way: when an export edition shares a Title with
        its domestic original, the domestic model heads the Title — the year
        tiebreak alone can't guarantee that for same-year pairs.

        Single source for that identity/order rule. Callers layer their own
        ``select_related`` / ``prefetch_related`` for their read shape, and
        :meth:`Title.first_model_subquery` correlates it with
        ``title=OuterRef("pk")``. Keeping it in one place stops the subquery, the
        title/card prefetches and the kiosk typeahead from drifting apart.
        """
        # Type set derived from RELATIONSHIP_TYPE_BEHAVIOR (never named
        # inline) so a new relationship type must classify itself before it
        # can influence Title-representative ordering.
        copy_edge = models.Exists(
            ModelRelationship.objects.filter(
                machine_model=models.OuterRef("pk"),
                relationship_type__in=SUBORDINATING_RELATIONSHIP_TYPES,
            )
        )
        is_copy = models.Case(
            models.When(
                models.Q(export_edition_of__isnull=False) | models.Q(copy_edge),
                then=models.Value(1),
            ),
            default=models.Value(0),
            output_field=models.IntegerField(),
        )
        return (
            cls.objects.active()
            .filter(variant_of__isnull=True)
            .alias(_is_subordinate_copy=is_copy)
            .order_by(*_FIRST_MODEL_ORDER)
        )

    @classmethod
    def first_models_by_title(cls) -> models.QuerySet[MachineModel]:
        """:meth:`first_model_candidates` regrouped for a **per-title rollup**:
        same candidate set, same rule, re-sorted so each title's rows are
        contiguous and its representative is the first row of its group.

        For callers that need every title's representative at once and would
        otherwise pay for the correlated :meth:`Title.first_model_subquery` per
        title — one ordered scan, take the first row per ``title_id`` in Python.
        The manufacturer facet count does exactly that; going through here is
        what keeps its representative identical to the one the manufacturer
        *filter* resolves through the subquery.
        """
        return cls.first_model_candidates().order_by("title_id", *_FIRST_MODEL_ORDER)

    @property
    def inbound_relationship_sources(self) -> models.QuerySet[MachineModel]:
        """Models whose relationship edges target this model.

        The read surface behind the ``soft_delete_usage_blockers`` entry: the
        walk needs a lifecycle queryset (it applies ``.active()``), and the
        edge row itself has none, so this hops through ``target_machine`` to
        the owning source models.
        """
        return MachineModel.objects.filter(relationships__target_machine=self)

    @classmethod
    def non_variant_models_q(cls) -> models.Q:
        """Some lists in the catalog only show models that are gameplay-distinct.
        These lists don't show cosmetic variants (``variant_of`` set).
        """
        return models.Q(variant_of__isnull=True)

    @classmethod
    def sitemap_queryset(cls) -> models.QuerySet[Self]:
        # Single-Model-Title rule (docs/SingleModelTitles.md): a Title with
        # one active MachineModel collapses to the Title page and
        # ``/models/<slug>`` redirects there, so that Model has no indexable
        # URL to contribute. A variant counts as a sibling, which keeps an
        # original-plus-variant pair in. An indexable Model subroute would
        # force a per-route exclusion.
        has_active_sibling = (
            cls.objects.active()
            .filter(title=models.OuterRef("title"))
            .exclude(pk=models.OuterRef("pk"))
        )
        return super().sitemap_queryset().filter(models.Exists(has_active_sibling))

    def autocomplete_sublabel(self) -> str | None:
        """Disambiguate same-named models with a "manufacturer · year" line.

        Reads the manufacturer through ``corporate_entity`` (pre-joined via
        ``autocomplete_select_related``) and the model's own ``year`` field.
        """
        manufacturer = (
            self.corporate_entity.manufacturer.name if self.corporate_entity else None
        )
        return manufacturer_year_sublabel(manufacturer, self.year)

    def claim_display_label(self) -> str:
        """Concise label when this model is the target of another claim."""
        manufacturer = (
            self.corporate_entity.manufacturer.name if self.corporate_entity else None
        )
        context = " ".join(
            part
            for part in (
                manufacturer,
                str(self.year) if self.year is not None else None,
            )
            if part
        )
        return f"{self.name} ({context})" if context else self.name

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
