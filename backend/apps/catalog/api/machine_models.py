"""Models (machine models) router — list, detail, and claim-patch endpoints."""

from collections.abc import Iterable
from typing import Any

from django.db.models import F, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Query, Router, Schema
from ninja.decorators import decorate_view
from ninja.pagination import paginate
from ninja.responses import Status
from ninja.security import django_auth
from pydantic import Field

from apps.catalog.engine.rich_text import describe
from apps.claim_edit.claim_write import (
    ClaimSpec,
    execute_claims,
    plan_scalar_field_claims,
    raise_form_error,
)
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.exceptions import StructuredValidationError
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q, is_deleted
from apps.core.pagination import NamedPageNumberPagination
from apps.core.schemas import (
    ErrorDetailSchema,
    RateLimitErrorSchema,
    ValidationErrorSchema,
)
from apps.core.types import JsonBody
from apps.media.helpers import displayed_primary_media, media_prefetch
from apps.provenance.helpers import claims_prefetch
from apps.provenance.models import ChangeSetAction
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    EDIT_RATE_LIMIT_SPEC,
    rate_limited,
)
from apps.provenance.schemas import (
    AttributionSchema,
    ChangeSetInputSchema,
)

from ..engine.entity_api.delete import (
    SoftDeleteBlockedError,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)
from ..engine.entity_api.own_media import own_media
from ..engine.query.constants import DEFAULT_PAGE_SIZE
from ..models import (
    Cabinet,
    Credit,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    GameFormat,
    Location,
    MachineModel,
    MachineModelGameplayFeature,
    ModelExportMarket,
    ModelRelationship,
    ProductionStatus,
    RewardType,
    System,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
    Theme,
)
from ..models.export_market import COUNTRY_TARGET_FILTER
from .edit_claims import (
    plan_abbreviation_claims,
    plan_credit_claims,
    plan_export_market_claims,
    plan_gameplay_feature_claims,
    plan_m2m_claims,
    plan_model_relationship_claims,
)
from .helpers import (
    _extract_variant_features,
    _get_feature_descendant_slugs,
    displayed_model_abbreviations,
    serialize_credit,
    serialize_title_machine,
)
from .images import (
    extract_image_attribution,
    extract_image_urls,
    fetch_model_media_map,
)
from .schemas import (
    LICENSE_STATUS_TO_LITERAL,
    RELATIONSHIP_TYPE_TO_LITERAL,
    AlreadyDeletedSchema,
    CreditSchema,
    DeleteResponseSchema,
    EditOptionSchema,
    EntityDetailSchema,
    EntityRef,
    GameplayFeatureRef,
    LicenseStatusLiteral,
    ModelClaimPatchSchema,
    ModelDeletePreviewSchema,
    ModelEditOptionsSchema,
    OwnMediaSchema,
    RelationshipTypeLiteral,
    SoftDeleteBlockedSchema,
    TitleModelSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ModelListItemSchema(Schema):
    """A machine model in list results."""

    name: str = Field(description="The model's display name.")
    slug: str = Field(description="The model's URL slug.")
    manufacturer: EntityRef | None = Field(
        None, description="The model's manufacturer."
    )
    year: int | None = Field(None, description="Release year, if known.")
    thumbnail_url: str | None = Field(
        None, description="URL of a thumbnail image, if available."
    )


class ModelVariantSchema(Schema):
    name: str
    public_id: str
    year: int | None = None
    variant_features: list[str] = []
    # Variants are same-maker cosmetic editions by definition, so this usually
    # matches the subject and stays hidden — but nothing enforces that, so the
    # ref carries the maker to disambiguate the anomaly like every other lineage
    # link rather than being the one surface that structurally can't.
    manufacturer: EntityRef | None = None


class ModelRef(Schema):
    """A reference to a machine model by its public id, with optional year and
    manufacturer. The manufacturer lets a reader distinguish same-named lineage
    links (e.g. a game and the bootlegs that copied its name) whose surfaces
    don't otherwise show a maker."""

    name: str
    public_id: str
    year: int | None = None
    manufacturer: EntityRef | None = None


class ModelRelationshipSchema(Schema):
    """One typed relationship edge on a model (copy / conversion / kit).

    ``target_machine`` is set when the target is seeded (renders as a link);
    ``target_label`` is the plain-text descriptor otherwise (renders unlinked).
    Exactly one is populated.
    """

    relationship_type: RelationshipTypeLiteral = Field(description="Edge type.")
    license_status: LicenseStatusLiteral = Field(description="Authorization status.")
    target_machine: ModelRef | None = None
    target_label: str = ""


class ModelExportMarketSchema(Schema):
    """One export-market row on a model (see Exports.md).

    ``target_location`` is set when the market is a seeded country (renders as
    a link to its location page); ``target_label`` is the free-text region
    descriptor otherwise ("Europe", unlinked). Both empty is the legal
    unknown-market row — the row itself says "built for export".
    """

    target_location: EntityRef | None = Field(
        None,
        description=("The destination country; public_id is its location_path."),
    )
    target_label: str = ""


class InboundModelRelationshipSchema(Schema):
    """One typed relationship edge *pointing at* this model — the reverse of
    :class:`ModelRelationshipSchema`, read through the ``inbound_relationships``
    accessor. Only machine-target edges have an inbound side (label targets
    aren't seeded rows), so the source is always a resolved ``ModelRef``.
    """

    relationship_type: RelationshipTypeLiteral = Field(description="Edge type.")
    license_status: LicenseStatusLiteral = Field(description="Authorization status.")
    source_machine: ModelRef = Field(
        description="The model this edge belongs to — the copy/conversion/kit."
    )


def _manufacturer_ref(pm: MachineModel | None) -> EntityRef | None:
    """The model's manufacturer as an `EntityRef`, resolved via its corporate
    entity (the manufacturer is a property of the maker, not the model)."""
    if pm is None:
        return None
    mfr = (
        pm.corporate_entity.manufacturer
        if pm.corporate_entity and pm.corporate_entity.manufacturer
        else None
    )
    return EntityRef(name=mfr.name, public_id=mfr.public_id) if mfr else None


def _required_model_ref(pm: MachineModel) -> ModelRef:
    """Build a `ModelRef` for a known-present related model."""
    return ModelRef(
        name=pm.name,
        public_id=pm.public_id,
        year=pm.year,
        manufacturer=_manufacturer_ref(pm),
    )


def _model_ref(pm: MachineModel | None) -> ModelRef | None:
    """Build a `ModelRef` for a nullable related model (e.g. `variant_of`), or `None`."""
    return _required_model_ref(pm) if pm is not None else None


def _model_refs(models: Iterable[MachineModel]) -> list[ModelRef]:
    """Build `ModelRef`s for a related-model collection (e.g. `conversions`)."""
    return [_required_model_ref(pm) for pm in models]


class ModelDetailSchema(EntityDetailSchema, OwnMediaSchema):
    slug: str
    manufacturer: EntityRef | None = None
    corporate_entity: EntityRef | None = None
    year: int | None = None
    month: int | None = None
    technology_generation: EntityRef | None = None
    technology_subgeneration: EntityRef | None = None
    display_type: EntityRef | None = None
    player_count: int | None = None
    themes: list[EntityRef] = []
    production_quantity: str
    system: EntityRef | None = None
    flipper_count: int | None = None
    ipdb_id: int | None = None
    opdb_id: str | None = None
    pinside_id: str | None = None
    manufacturer_model_identifier: str | None = None
    abbreviations: list[str] = []
    extra_data: JsonBody
    credits: list[CreditSchema]
    thumbnail_url: str | None = None
    hero_image_url: str | None = None
    image_attribution: AttributionSchema | None = None
    variant_features: list[str] = []
    variants: list[ModelVariantSchema] = []
    title: EntityRef
    cabinet: EntityRef | None = None
    game_format: EntityRef | None = None
    production_status: EntityRef | None = None
    display_subtype: EntityRef | None = None
    gameplay_features: list[GameplayFeatureRef] = []
    tags: list[EntityRef] = []
    reward_types: list[EntityRef] = []
    franchise: EntityRef | None = None
    series: EntityRef | None = None
    variant_of: ModelRef | None = None
    variant_siblings: list[ModelVariantSchema] = []
    remake_of: ModelRef | None = None
    remakes: list[ModelRef] = []
    export_edition_of: ModelRef | None = None
    export_editions: list[ModelRef] = []
    export_markets: list[ModelExportMarketSchema] = []
    relationships: list[ModelRelationshipSchema] = []
    inbound_relationships: list[InboundModelRelationshipSchema] = []
    title_models: list[TitleModelSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_model_list_qs(
    manufacturer: str = "",
    type: str = "",
    subgeneration: str = "",
    display: str = "",
    display_subtype: str = "",
    feature: str = "",
    reward_type: str = "",
    game_format: str = "",
    cabinet: str = "",
    production_status: str = "",
    tag: str = "",
    year_min: int | None = None,
    year_max: int | None = None,
    person: str = "",
    include_variants: bool = False,
    ordering: str = "-year",
) -> QuerySet[MachineModel]:
    qs = (
        MachineModel.objects.active()
        .select_related(
            "corporate_entity__manufacturer",
            "title",
        )
        .prefetch_related(media_prefetch())
    )
    # include_variants opts out of the variant collapse for browses where a
    # variant's own value is the point — e.g. production-status, where an
    # announced LE of an already-shipped Premium must appear as its own row.
    if not include_variants:
        qs = qs.filter(MachineModel.non_variant_models_q())

    if manufacturer:
        qs = qs.filter(corporate_entity__manufacturer__slug=manufacturer)
    if type:
        qs = qs.filter(technology_generation__slug=type)
    if subgeneration:
        qs = qs.filter(
            Q(technology_subgeneration__slug=subgeneration)
            | Q(system__technology_subgeneration__slug=subgeneration)
        )
    if display:
        qs = qs.filter(display_type__slug=display)
    if display_subtype:
        qs = qs.filter(display_subtype__slug=display_subtype)
    if feature:
        qs = qs.filter(
            gameplay_features__slug__in=_get_feature_descendant_slugs(feature)
        )
    if reward_type:
        qs = qs.filter(reward_types__slug=reward_type)
    if game_format:
        qs = qs.filter(game_format__slug=game_format)
    if cabinet:
        qs = qs.filter(cabinet__slug=cabinet)
    if production_status:
        qs = qs.filter(production_status__slug=production_status)
    if tag:
        qs = qs.filter(tags__slug=tag)
    if year_min is not None:
        qs = qs.filter(year__gte=year_min)
    if year_max is not None:
        qs = qs.filter(year__lte=year_max)
    if person:
        qs = qs.filter(credits__person__slug=person).distinct()

    ordering_map = {
        "name": [F("name").asc()],
        "-name": [F("name").desc()],
        "year": [F("year").asc(nulls_last=True)],
        "-year": [F("year").desc(nulls_last=True)],
    }
    order_exprs = ordering_map.get(ordering, ordering_map["-year"])
    qs = qs.order_by(*order_exprs, "name")

    return qs


def _serialize_model_list(
    pm: MachineModel, *, min_rank: int | None = None
) -> ModelListItemSchema:
    thumbnail_url, _ = extract_image_urls(
        pm.extra_data or {}, displayed_primary_media(pm), min_rank=min_rank
    )
    return ModelListItemSchema(
        name=pm.name,
        slug=pm.slug,
        manufacturer=_manufacturer_ref(pm),
        year=pm.year,
        thumbnail_url=thumbnail_url,
    )


@own_media(MachineModel)
def _serialize_model_detail(pm: MachineModel) -> ModelDetailSchema:
    """Serialize a MachineModel into the detail response schema.

    Expects *pm* to have been fetched with prefetch_related for credits
    (with select_related("person")) and claims (to_attr="active_claims").

    The own-media gallery (``uploaded_media``) is filled by the ``own_media``
    decorator. This body derives the *displayed-primary* subset (via
    ``displayed_primary_media(pm)``) that drives the domain thumbnail/hero
    (``extract_image_*`` over ``extra_data``), which stays domain.
    """
    min_rank = get_minimum_display_rank()

    credits = [serialize_credit(c) for c in pm.credits.all()]

    primary = displayed_primary_media(pm)
    thumbnail_url, hero_image_url = extract_image_urls(
        pm.extra_data or {}, primary or None, min_rank=min_rank
    )
    image_attribution = extract_image_attribution(pm.extra_data or {}, primary or None)
    variant_features = _extract_variant_features(pm.extra_data or {})

    variants = [
        ModelVariantSchema(
            name=v.name,
            public_id=v.public_id,
            year=v.year,
            variant_features=_extract_variant_features(v.extra_data or {}),
            manufacturer=_manufacturer_ref(v),
        )
        for v in pm.variants.all()
    ]

    # Build sibling variants: other variants of the same parent.
    variant_siblings: list[ModelVariantSchema] = []
    if pm.variant_of_id is not None:
        parent = pm.variant_of
        assert parent is not None  # narrowed by variant_of_id check above
        variant_siblings = [
            ModelVariantSchema(
                name=sib.name,
                public_id=sib.public_id,
                year=sib.year,
                variant_features=_extract_variant_features(sib.extra_data or {}),
                manufacturer=_manufacturer_ref(sib),
            )
            for sib in parent.variants.all()
            if sib.pk != pm.pk
        ]

    # Resolve technology subgeneration: direct on model, or inherited from system.
    subgen = pm.technology_subgeneration or (
        pm.system.technology_subgeneration
        if pm.system and pm.system.technology_subgeneration
        else None
    )

    return ModelDetailSchema(
        name=pm.name,
        public_id=pm.public_id,
        last_modified=pm.last_modified,
        slug=pm.slug,
        description=describe(pm),
        manufacturer=_manufacturer_ref(pm),
        corporate_entity=(
            EntityRef(
                name=pm.corporate_entity.name, public_id=pm.corporate_entity.public_id
            )
            if pm.corporate_entity
            else None
        ),
        year=pm.year,
        month=pm.month,
        technology_generation=(
            EntityRef(
                name=pm.technology_generation.name,
                public_id=pm.technology_generation.public_id,
            )
            if pm.technology_generation
            else None
        ),
        technology_subgeneration=(
            EntityRef(name=subgen.name, public_id=subgen.public_id) if subgen else None
        ),
        display_type=(
            EntityRef(name=pm.display_type.name, public_id=pm.display_type.public_id)
            if pm.display_type
            else None
        ),
        player_count=pm.player_count,
        themes=[EntityRef(name=t.name, public_id=t.public_id) for t in pm.themes.all()],
        production_quantity=pm.production_quantity,
        system=(
            EntityRef(name=pm.system.name, public_id=pm.system.public_id)
            if pm.system
            else None
        ),
        flipper_count=pm.flipper_count,
        ipdb_id=pm.ipdb_id,
        opdb_id=pm.opdb_id,
        pinside_id=pm.pinside_id,
        manufacturer_model_identifier=pm.manufacturer_model_identifier,
        abbreviations=displayed_model_abbreviations(pm),
        extra_data=pm.extra_data or {},
        credits=credits,
        thumbnail_url=thumbnail_url,
        hero_image_url=hero_image_url,
        image_attribution=image_attribution,
        variant_features=variant_features,
        variants=variants,
        variant_of=_model_ref(pm.variant_of),
        variant_siblings=variant_siblings,
        remake_of=_model_ref(pm.remake_of),
        remakes=_model_refs(pm.remakes.all()),
        export_edition_of=_model_ref(pm.export_edition_of),
        export_editions=_model_refs(pm.export_editions.all()),
        export_markets=[
            ModelExportMarketSchema(
                target_location=(
                    EntityRef(
                        name=market.target_market_location.name,
                        public_id=market.target_market_location.public_id,
                    )
                    if market.target_market_location
                    else None
                ),
                target_label=market.target_market_label,
            )
            for market in pm.export_markets.all()
        ],
        relationships=[
            ModelRelationshipSchema(
                relationship_type=RELATIONSHIP_TYPE_TO_LITERAL[edge.relationship_type],
                license_status=LICENSE_STATUS_TO_LITERAL[edge.license_status],
                target_machine=_model_ref(edge.target_machine),
                target_label=edge.target_label,
            )
            for edge in pm.relationships.all()
        ],
        inbound_relationships=[
            InboundModelRelationshipSchema(
                relationship_type=RELATIONSHIP_TYPE_TO_LITERAL[edge.relationship_type],
                license_status=LICENSE_STATUS_TO_LITERAL[edge.license_status],
                source_machine=_required_model_ref(edge.machine_model),
            )
            for edge in pm.inbound_relationships.all()
        ],
        title=EntityRef(name=pm.title.name, public_id=pm.title.public_id),
        cabinet=(
            EntityRef(name=pm.cabinet.name, public_id=pm.cabinet.public_id)
            if pm.cabinet
            else None
        ),
        game_format=(
            EntityRef(name=pm.game_format.name, public_id=pm.game_format.public_id)
            if pm.game_format
            else None
        ),
        # Always serialize the real value (incl. ``produced``): the Model editor
        # consumes this serializer as ``data.profile`` → ``initialData``, so
        # suppressing here would blank the picker over a real claim. The
        # produced/null hide lives in the frontend (ModelSpecsSidebar).
        production_status=(
            EntityRef(
                name=pm.production_status.name,
                public_id=pm.production_status.public_id,
            )
            if pm.production_status
            else None
        ),
        display_subtype=(
            EntityRef(
                name=pm.display_subtype.name, public_id=pm.display_subtype.public_id
            )
            if pm.display_subtype
            else None
        ),
        gameplay_features=[
            GameplayFeatureRef(
                name=t.gameplayfeature.name,
                public_id=t.gameplayfeature.public_id,
                count=t.count,
            )
            for t in pm.machinemodelgameplayfeature_set.all()
        ],
        tags=[EntityRef(name=t.name, public_id=t.public_id) for t in pm.tags.all()],
        reward_types=[
            EntityRef(name=rt.name, public_id=rt.public_id)
            for rt in pm.reward_types.all()
        ],
        franchise=(
            EntityRef(
                name=pm.title.franchise.name, public_id=pm.title.franchise.public_id
            )
            if pm.title and pm.title.franchise
            else None
        ),
        series=(
            EntityRef(name=pm.title.series.name, public_id=pm.title.series.public_id)
            if pm.title and pm.title.series
            else None
        ),
        title_models=_serialize_title_models(pm, min_rank=min_rank),
    )


def _serialize_title_models(
    pm: MachineModel, *, min_rank: int
) -> list[TitleModelSchema]:
    if pm.title is None:
        return []
    siblings = [s for s in pm.title.machine_models.all() if s.variant_of_id is None]
    media_by_model = fetch_model_media_map(s.pk for s in siblings)
    return [
        serialize_title_machine(
            sibling, min_rank=min_rank, media_by_model=media_by_model
        )
        for sibling in siblings
    ]


def _model_detail_qs() -> QuerySet[MachineModel]:
    """Return the queryset used for model detail / patch endpoints."""
    return (
        MachineModel.objects.active()
        .select_related(
            "corporate_entity__manufacturer",
            "title",
            "title__franchise",
            "title__series",
            "system",
            "system__technology_subgeneration",
            "technology_generation",
            "technology_subgeneration",
            "display_type",
            "display_subtype",
            "cabinet",
            "game_format",
            "production_status",
            # `__corporate_entity__manufacturer` so the lineage ModelRefs can
            # carry a maker for disambiguating same-named links without an
            # N+1 per related row.
            "variant_of__corporate_entity__manufacturer",
            "remake_of__corporate_entity__manufacturer",
            "export_edition_of__corporate_entity__manufacturer",
        )
        .prefetch_related(
            # Reverse lineage lists and inbound edges filter to LIVE referrers:
            # deleting the FK *source* (a variant, remake, export edition, or
            # an edge's owning model) is never delete-blocked — PROTECT and the
            # usage blockers guard the target direction only — so an unfiltered
            # list would link the deleted model's 404. Forward FKs need no
            # filter: their targets can't be soft-deleted while referenced.
            #
            # Variants and sibling variants also carry a maker; select the
            # manufacturer join so building their refs stays query-free.
            Prefetch(
                "variants",
                queryset=MachineModel.objects.active().select_related(
                    "corporate_entity__manufacturer"
                ),
            ),
            Prefetch(
                "variant_of__variants",
                queryset=MachineModel.objects.active().select_related(
                    "corporate_entity__manufacturer"
                ),
            ),
            # Relationship edges render their machine target as a ModelRef
            # with a maker; join it here so the ref build stays query-free.
            # (Outbound targets are delete-blocked while this model is live,
            # so no liveness filter is needed on the target side.)
            Prefetch(
                "relationships",
                queryset=ModelRelationship.objects.select_related(
                    "target_machine__corporate_entity__manufacturer"
                ),
            ),
            # Inbound edges render their source model the same way; the edge
            # row itself has no lifecycle, so liveness rides its owner.
            Prefetch(
                "inbound_relationships",
                queryset=ModelRelationship.objects.filter(
                    active_status_q("machine_model")
                ).select_related("machine_model__corporate_entity__manufacturer"),
            ),
            # Reverse lineage lists render as ModelRefs with a maker; select the
            # manufacturer join here to keep the ref build query-free.
            Prefetch(
                "remakes",
                queryset=MachineModel.objects.active().select_related(
                    "corporate_entity__manufacturer"
                ),
            ),
            Prefetch(
                "export_editions",
                queryset=MachineModel.objects.active().select_related(
                    "corporate_entity__manufacturer"
                ),
            ),
            # Export-market rows render their country as a linked ref; join it
            # here so the ref build stays query-free.
            Prefetch(
                "export_markets",
                queryset=ModelExportMarket.objects.select_related(
                    "target_market_location"
                ),
            ),
            "themes",
            Prefetch(
                "machinemodelgameplayfeature_set",
                queryset=MachineModelGameplayFeature.objects.select_related(
                    "gameplayfeature"
                ).order_by("gameplayfeature__name"),
            ),
            "tags",
            "reward_types",
            "abbreviations",
            # Title's abbreviations drive the read-time dedup in
            # displayed_model_abbreviations.
            "title__abbreviations",
            Prefetch(
                "title__machine_models",
                queryset=MachineModel.objects.active()
                .filter(MachineModel.non_variant_models_q())
                .select_related(
                    "corporate_entity__manufacturer", "technology_generation"
                )
                # Live variants only — same reverse-liveness rule as above.
                .prefetch_related(
                    Prefetch("variants", queryset=MachineModel.objects.active())
                )
                .order_by("year", "name"),
            ),
            Prefetch(
                "credits",
                queryset=Credit.objects.filter(model__isnull=False).select_related(
                    "person", "role"
                ),
            ),
            claims_prefetch(),
            media_prefetch(),
        )
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

models_router = Router(tags=["models"])


class ModelListPagination(NamedPageNumberPagination):
    response_name = "ModelListSchema"


class ModelFilterQuerySchema(Schema):
    """Every /models filter dimension as query params. All filters combine with AND."""

    manufacturer: str = Field(
        "", description="Manufacturer slug (see `GET /api/manufacturers/`)."
    )
    type: str = Field(
        "",
        description="Technology-generation slug (see `GET /api/technology-generations/`).",
    )
    subgeneration: str = Field(
        "",
        description=(
            "Technology-subgeneration slug. Matches the model's own subgeneration "
            "or its system's."
        ),
    )
    display: str = Field(
        "", description="Display-type slug (see `GET /api/display-types/`)."
    )
    display_subtype: str = Field("", description="Display-subtype slug.")
    feature: str = Field(
        "",
        description=(
            "Gameplay-feature slug (see `GET /api/gameplay-features/`). Also matches "
            "its sub-features."
        ),
    )
    reward_type: str = Field(
        "", description="Reward-type slug (see `GET /api/reward-types/`)."
    )
    game_format: str = Field(
        "", description="Game-format slug (see `GET /api/game-formats/`)."
    )
    cabinet: str = Field("", description="Cabinet slug (see `GET /api/cabinets/`).")
    production_status: str = Field(
        "",
        description="Production-status slug (see `GET /api/production-statuses/`).",
    )
    tag: str = Field("", description="Tag slug (see `GET /api/tags/`).")
    year_min: int | None = Field(None, description="Earliest release year, inclusive.")
    year_max: int | None = Field(None, description="Latest release year, inclusive.")
    person: str = Field(
        "",
        description=(
            "Person slug (see `GET /api/people/`). Matches models this person is "
            "credited on."
        ),
    )
    include_variants: bool = Field(
        False,
        description=(
            "Include cosmetic variants, which are otherwise collapsed into their "
            "parent model. Default false."
        ),
    )
    ordering: str = Field(
        "-year",
        description=(
            "Sort order: `name`, `-name`, `year` or `-year`. Defaults to `-year` "
            "(newest first)."
        ),
    )


@models_router.get("/", response=list[ModelListItemSchema])
@paginate(ModelListPagination, page_size=DEFAULT_PAGE_SIZE)
def list_models(
    request: HttpRequest, filters: Query[ModelFilterQuerySchema]
) -> list[ModelListItemSchema]:
    """Machine models, paginated. Narrow with the filters. Ordered by the ``ordering``
    param (newest first by default).

    All filters combine with AND."""
    qs = _build_model_list_qs(
        manufacturer=filters.manufacturer,
        type=filters.type,
        subgeneration=filters.subgeneration,
        display=filters.display,
        display_subtype=filters.display_subtype,
        feature=filters.feature,
        reward_type=filters.reward_type,
        game_format=filters.game_format,
        cabinet=filters.cabinet,
        production_status=filters.production_status,
        tag=filters.tag,
        year_min=filters.year_min,
        year_max=filters.year_max,
        person=filters.person,
        include_variants=filters.include_variants,
        ordering=filters.ordering,
    )
    min_rank = get_minimum_display_rank()
    return [_serialize_model_list(pm, min_rank=min_rank) for pm in qs]


class ModelRecentSchema(Schema):
    name: str
    slug: str
    manufacturer_name: str | None = None
    year: int | None = None
    thumbnail_url: str | None = None


# Website-only (homepage widget), not external catalog data — kept out of the
# public API docs via tags=["private"].
@models_router.get("/recent/", response=list[ModelRecentSchema], tags=["private"])
@decorate_view(cache_control(no_cache=True))
def list_recent_models(request: HttpRequest) -> list[ModelRecentSchema]:
    """Return the 3 newest non-variant models, one per title."""
    qs = (
        MachineModel.objects.active()
        .filter(MachineModel.non_variant_models_q())
        .select_related("corporate_entity__manufacturer")
        .order_by(
            F("year").desc(nulls_last=True),
            F("month").desc(nulls_last=True),
            "-updated_at",
        )[:20]  # generous LIMIT — we only need 3 unique titles
    )
    min_rank = get_minimum_display_rank()
    candidates = list(qs)
    media_by_model = fetch_model_media_map(m.pk for m in candidates)
    results: list[ModelRecentSchema] = []
    seen_titles: set[int | None] = set()
    for m in candidates:
        title_id = m.title_id
        if title_id in seen_titles:
            continue
        seen_titles.add(title_id)
        thumbnail_url, _ = extract_image_urls(
            m.extra_data or {}, media_by_model.get(m.pk), min_rank=min_rank
        )
        results.append(
            ModelRecentSchema(
                name=m.name,
                slug=m.slug,
                manufacturer_name=(
                    m.corporate_entity.manufacturer.name
                    if m.corporate_entity and m.corporate_entity.manufacturer
                    else None
                ),
                year=m.year,
                thumbnail_url=thumbnail_url,
            )
        )
        if len(results) == 3:
            break
    return results


# Serves the in-app edit form, not external consumers — kept out of the public
# API docs via tags=["private"].
@models_router.get("/edit-options/", response=ModelEditOptionsSchema, tags=["private"])
@decorate_view(cache_control(no_cache=True))
def get_model_edit_options(request: HttpRequest) -> ModelEditOptionsSchema:
    """Return all dropdown options for the MachineModel edit form."""

    def _opts(qs: QuerySet[Any]) -> list[EditOptionSchema]:
        return [EditOptionSchema(slug=obj.slug, label=obj.name) for obj in qs]

    return ModelEditOptionsSchema(
        tags=_opts(Tag.objects.active().order_by("name")),
        reward_types=_opts(
            RewardType.objects.active().order_by("display_order", "name")
        ),
        technology_generations=_opts(
            TechnologyGeneration.objects.active().order_by("display_order", "name")
        ),
        technology_subgenerations=_opts(
            TechnologySubgeneration.objects.active().order_by("display_order", "name")
        ),
        display_types=_opts(
            DisplayType.objects.active().order_by("display_order", "name")
        ),
        display_subtypes=_opts(
            DisplaySubtype.objects.active().order_by("display_order", "name")
        ),
        cabinets=_opts(Cabinet.objects.active().order_by("display_order", "name")),
        game_formats=_opts(
            GameFormat.objects.active().order_by("display_order", "name")
        ),
        production_statuses=_opts(
            ProductionStatus.objects.active().order_by("display_order", "name")
        ),
        systems=_opts(System.objects.active().order_by("name")),
        credit_roles=_opts(
            CreditRole.objects.active().order_by("display_order", "name")
        ),
        # Root locations only (COUNTRY_TARGET_FILTER): the export-market
        # editor's country picker. slug carries the location_path, which
        # equals the slug for root locations.
        countries=[
            EditOptionSchema(slug=loc.location_path, label=loc.name)
            for loc in Location.objects.active()
            .filter(**dict(COUNTRY_TARGET_FILTER.lookups))
            .order_by("name")
        ],
    )


_SELF_REF_FIELDS: frozenset[str] = frozenset(
    {"variant_of", "remake_of", "export_edition_of"}
)


@models_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: ModelDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_model_claims(
    request: HttpRequest, public_id: str, data: ModelClaimPatchSchema
) -> ModelDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve the model."""
    pm = get_object_or_404(
        MachineModel.objects.active()
        .select_related("title")
        .prefetch_related(
            "themes",
            "tags",
            "reward_types",
            "machinemodelgameplayfeature_set__gameplayfeature",
            "abbreviations",
            # Title's abbreviations drive the abbreviation edit-diff dedup.
            "title__abbreviations",
            "credits__person",
            "credits__role",
            # The relationship planner diffs against current edges.
            "relationships",
            # The export-market planner diffs against current rows.
            "export_markets",
        ),
        **{MachineModel.public_id_field: public_id},
    )

    specs = (
        plan_scalar_field_claims(
            MachineModel,
            data.fields,
            entity=pm,
            inline_citations=data.inline_citations,
        )
        if data.fields
        else []
    )

    for field_name, value in data.fields.items():
        if field_name in _SELF_REF_FIELDS and value == public_id:
            raise StructuredValidationError(
                message="A model cannot reference itself.",
                field_errors={field_name: "A model cannot reference itself."},
            )

    if data.themes is not None:
        specs.extend(
            plan_m2m_claims(
                pm,
                set(data.themes),
                target_model=Theme,
                claim_field_name="theme",
                m2m_attr="themes",
            )
        )
    if data.tags is not None:
        specs.extend(
            plan_m2m_claims(
                pm,
                set(data.tags),
                target_model=Tag,
                claim_field_name="tag",
                m2m_attr="tags",
            )
        )
    if data.reward_types is not None:
        specs.extend(
            plan_m2m_claims(
                pm,
                set(data.reward_types),
                target_model=RewardType,
                claim_field_name="reward_type",
                m2m_attr="reward_types",
            )
        )
    if data.gameplay_features is not None:
        specs.extend(plan_gameplay_feature_claims(pm, data.gameplay_features))
    if data.credits is not None:
        specs.extend(plan_credit_claims(pm, data.credits))
    if data.abbreviations is not None:
        specs.extend(plan_abbreviation_claims(pm, data.abbreviations))
    if data.relationships is not None:
        specs.extend(plan_model_relationship_claims(pm, data.relationships))
    if data.export_markets is not None:
        specs.extend(plan_export_market_claims(pm, data.export_markets))

    if not specs:
        raise_form_error("No changes provided.")

    execute_claims(
        pm,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
    )

    pm = get_object_or_404(
        _model_detail_qs(), **{MachineModel.public_id_field: pm.public_id}
    )
    return _serialize_model_detail(pm)


# ---------------------------------------------------------------------------
# Delete / restore
# ---------------------------------------------------------------------------


@models_router.get(
    "/{path:public_id}/delete-preview/",
    auth=django_auth,
    response=ModelDeletePreviewSchema,
    tags=["private"],
)
def model_delete_preview(
    request: HttpRequest, public_id: str
) -> ModelDeletePreviewSchema:
    """Return the impact summary used by the delete confirmation screen."""
    pm = get_object_or_404(
        MachineModel.objects.active().select_related("title"),
        **{MachineModel.public_id_field: public_id},
    )
    plan = plan_soft_delete(pm)
    changeset_count = 0 if plan.is_blocked else count_entity_changesets(pm)
    return ModelDeletePreviewSchema(
        name=pm.name,
        slug=pm.slug,
        parent=EntityRef(name=pm.title.name, public_id=pm.title.public_id),
        changeset_count=changeset_count,
        blocked_by=[serialize_blocking_referrer(b) for b in plan.blockers],
    )


@models_router.post(
    "/{path:public_id}/delete/",
    auth=django_auth,
    response={
        200: DeleteResponseSchema,
        422: SoftDeleteBlockedSchema | AlreadyDeletedSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_DELETE)
@rate_limited(DELETE_RATE_LIMIT_SPEC)
def delete_model(
    request: HttpRequest, public_id: str, data: ChangeSetInputSchema
) -> DeleteResponseSchema | Status[SoftDeleteBlockedSchema | AlreadyDeletedSchema]:
    """Soft-delete a MachineModel.

    Writes a single user ChangeSet with ``action=delete`` containing one
    ``status=deleted`` claim. Rate-limited per user on the ``delete`` bucket
    (5/day; staff bypass). Blocks with 422 when an active PROTECT referrer
    (a child variant, a model whose ``remake_of`` points here, an inbound
    relationship edge, …) would be left dangling. Never cascades to the
    parent Title — orphan Titles are supported by spec.
    """
    pm = get_object_or_404(
        MachineModel.objects.active(), **{MachineModel.public_id_field: public_id}
    )
    try:
        changeset, deleted = execute_soft_delete(
            pm, user=request.user, note=data.note, citations=data.citations
        )
    except SoftDeleteBlockedError as exc:
        return Status(
            422,
            SoftDeleteBlockedSchema(
                detail="Cannot delete: active references would be left dangling.",
                blocked_by=[serialize_blocking_referrer(b) for b in exc.blockers],
            ),
        )

    if changeset is None:
        return Status(422, AlreadyDeletedSchema(detail="Model is already deleted."))

    return DeleteResponseSchema(
        changeset_id=changeset.pk,
        affected_slugs=[e.slug for e in deleted if isinstance(e, MachineModel)],
    )


@models_router.post(
    "/{path:public_id}/restore/",
    auth=django_auth,
    response={
        200: ModelDetailSchema,
        422: ErrorDetailSchema,
        404: ErrorDetailSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_CREATE)
@rate_limited(CREATE_RATE_LIMIT_SPEC)
def restore_model(
    request: HttpRequest, public_id: str, data: ChangeSetInputSchema
) -> ModelDetailSchema | Status[ErrorDetailSchema]:
    """Write a fresh ``status=active`` claim on a soft-deleted Model.

    This is the "Restore" path (distinct from Undo, which inverts a specific
    delete ChangeSet). Shares the ``create`` rate-limit bucket. The parent
    Title is untouched — consistent with delete's no-cascade-to-parent rule.
    """
    # Bypass .active() — we're looking for soft-deleted models.
    pm = get_object_or_404(MachineModel, **{MachineModel.public_id_field: public_id})
    if not is_deleted(pm.status):
        return Status(422, ErrorDetailSchema(detail="Model is not deleted."))

    execute_claims(
        pm,
        [ClaimSpec(field_name="status", value="active")],
        user=request.user,
        action=ChangeSetAction.EDIT,
        note=data.note,
        citations=data.citations,
    )

    refreshed = get_object_or_404(
        _model_detail_qs(), **{MachineModel.public_id_field: public_id}
    )
    return _serialize_model_detail(refreshed)
