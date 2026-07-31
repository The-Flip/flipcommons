"""Taxonomy routers — technology generations, display types, and related lookups."""

from __future__ import annotations

from itertools import chain
from typing import Annotated, Any, TypeVar, cast

from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.params.functions import Path as PathParam
from ninja.security import django_auth
from pydantic import Field

from apps.catalog.engine.rich_text import build_rich_text
from apps.claim_edit.claim_write import execute_claims, plan_scalar_field_claims
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..engine.entity_api.create import register_entity_create
from ..engine.entity_api.delete import register_entity_delete_restore
from ..engine.entity_api.listing import paginated_list_response
from ..engine.query.constants import NameAliasQuery, NameQuery, PageParam
from ..models import (
    Cabinet,
    CatalogModel,
    Credit,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    GameFormat,
    MachineModel,
    Person,
    ProductionStatus,
    RewardType,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
)
from ._counts import bulk_title_counts_via_models
from ._typing import HasTitleCount
from .games import GameListSchema
from .images import extract_image_urls, fetch_model_media_map
from .people import PersonCardSchema
from .schemas import (
    ClaimPatchSchema,
    EntityDetailSchema,
    EntityRef,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaxonomySchema(EntityDetailSchema):
    """A catalog taxonomy entity (cabinet style, tag, reward type, …)."""

    slug: str = Field(description="The entity's URL slug.")
    display_order: int = Field(
        description="Editorial sort weight; lower values sort first."
    )
    aliases: list[str] = Field(
        [], description="Alternative names this entity is also known by."
    )


class TaxonomyWithTitleCountSchema(TaxonomySchema):
    """A taxonomy entity plus the number of titles associated with it."""

    title_count: int = Field(
        0, description="Number of titles associated with this entity."
    )


class _TaxonomyListPage(Schema):
    """Base for the per-entity flat-taxonomy page wrappers consumed by
    ``register_taxonomy_router``: ``items`` is this page's title-count rows;
    ``count`` is the total matching across all pages. Each entity subclasses
    this so it keeps its own named OpenAPI component (``CabinetListSchema``,
    …); pydantic inlines the inherited fields, so the wire schema is unchanged."""

    items: list[TaxonomyWithTitleCountSchema]
    count: int


class DisplayTypeListItemSchema(TaxonomyWithTitleCountSchema):
    subtypes: list[TaxonomyWithTitleCountSchema] = Field(
        [], description="This display type's subtypes."
    )


class TechnologyGenerationListItemSchema(TaxonomyWithTitleCountSchema):
    subgenerations: list[TaxonomyWithTitleCountSchema] = Field(
        [], description="This technology generation's subgenerations."
    )


# The two single-parent subtaxonomies expose their parent as a ref so the
# detail page can render the `Parent › Child` trail (the flat taxonomies have
# no parent; the DAG taxonomies — GameplayFeature, Theme — carry `parents`).
class DisplaySubtypeDetailSchema(TaxonomySchema):
    display_type: EntityRef


class TechnologySubgenerationDetailSchema(TaxonomySchema):
    technology_generation: EntityRef


# The detail-*page* payloads: the record plus page 1 of its games — the
# listing pinned to the taxonomy's dimension. Mutation responses keep the
# slim schemas above; only the page endpoints carry the embedded listing.
class TaxonomyDetailPageSchema(TaxonomySchema):
    games: GameListSchema


class DisplaySubtypeDetailPageSchema(DisplaySubtypeDetailSchema):
    games: GameListSchema


class TechnologySubgenerationDetailPageSchema(TechnologySubgenerationDetailSchema):
    games: GameListSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Constrained TypeVar over the concrete taxonomy model classes that
# share ``TaxonomySchema`` as their public shape. Constraints (not a bound)
# are required so each call site binds ``_TaxM`` to the specific concrete
# class — otherwise `type[_TaxM]` collapses to the common base
# ``CatalogModel`` and ``.objects.active()`` / attribute access are lost.
# Written with ``typing.TypeVar`` rather than PEP 695 syntax so the
# constraints aren't repeated on every generic function; the per-def
# UP047 suppression below covers the associated ruff rule.
_TaxM = TypeVar(
    "_TaxM",
    Cabinet,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    GameFormat,
    ProductionStatus,
    RewardType,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
)


def _serialize_taxonomy(
    obj: (
        Cabinet
        | CreditRole
        | DisplaySubtype
        | DisplayType
        | GameFormat
        | ProductionStatus
        | RewardType
        | Tag
        | TechnologyGeneration
        | TechnologySubgeneration
    ),
) -> TaxonomySchema:
    # RewardType is the only shared-schema taxonomy with an ``aliases``
    # reverse relation; the others share the schema purely for output
    # uniformity.
    aliases: list[str] = []
    if isinstance(obj, RewardType):
        aliases = [a.value for a in obj.aliases.all()]
    # Dual-use serializer: called from list endpoints (no claims prefetch)
    # and detail endpoints (claims_prefetch applied). `getattr` with None
    # lets build_rich_text skip attribution for list callers; detail
    # callers get full attribution. Don't replace with active_claims() —
    # it would raise on the list path.
    return TaxonomySchema(
        name=obj.name,
        public_id=obj.public_id,
        last_modified=obj.last_modified,
        slug=obj.slug,
        display_order=obj.display_order,
        description=build_rich_text(
            obj, "description", getattr(obj, "active_claims", None)
        ),
        aliases=aliases,
    )


def _serialize_display_subtype(obj: DisplaySubtype) -> DisplaySubtypeDetailSchema:
    return DisplaySubtypeDetailSchema(
        **_serialize_taxonomy(obj).model_dump(),
        display_type=EntityRef(
            name=obj.display_type.name, public_id=obj.display_type.public_id
        ),
    )


def _serialize_technology_subgeneration(
    obj: TechnologySubgeneration,
) -> TechnologySubgenerationDetailSchema:
    return TechnologySubgenerationDetailSchema(
        **_serialize_taxonomy(obj).model_dump(),
        technology_generation=EntityRef(
            name=obj.technology_generation.name,
            public_id=obj.technology_generation.public_id,
        ),
    )


def _flat_taxonomy_title_count() -> Count:
    """SQL twin of ``bulk_title_counts_via_models(pks, "<rel>")`` for the flat
    (non-DAG) taxonomies — all of which reverse to ``machine_models``: the count of
    distinct active Titles reached through active, non-variant models. Rides on the row
    as a ``title_count`` annotation so the paginated core's order+slice path reads it
    straight off the row; parity with the Python helper is pinned in
    ``test_api_catalog_list``."""
    return Count(
        "machine_models__title",
        filter=(
            Q(machine_models__variant_of__isnull=True)
            & active_status_q("machine_models")
            & active_status_q("machine_models__title")
        ),
        distinct=True,
    )


def _serialize_taxonomy_with_count(
    obj: Cabinet | GameFormat | ProductionStatus | RewardType | Tag,
    thumbnail: str | None = None,
) -> TaxonomyWithTitleCountSchema:
    """Row serializer for the paginated flat-taxonomy handlers: the shared
    ``TaxonomySchema`` body plus the ``title_count`` annotation read off the row.
    ``thumbnail`` is unused (these taxonomies carry no image) but is accepted to satisfy
    the core's ``RowSerializer`` signature."""
    return TaxonomyWithTitleCountSchema(
        **_serialize_taxonomy(obj).model_dump(),
        title_count=cast(HasTitleCount, obj).title_count,
    )


# Constrained TypeVar over the flat title-count taxonomies that route through
# ``register_taxonomy_router`` / ``_flat_taxonomy_list_qs``. RewardType is a flat
# title-count taxonomy too but is deliberately absent: its list is alias-aware and
# its detail schema is bespoke, so it keeps a hand-written router — excluding it
# makes passing it to the factory a type error. (``_serialize_taxonomy_with_count``
# still accepts RewardType for that bespoke list; a serializer over the wider union
# is assignable to the factory's narrower row-serializer slot.)
_FlatTaxM = TypeVar("_FlatTaxM", Cabinet, GameFormat, ProductionStatus, Tag)


def _flat_taxonomy_list_qs(model_cls: type[_FlatTaxM]) -> QuerySet[_FlatTaxM]:  # noqa: UP047
    """Active rows of *model_cls* carrying the shared ``title_count`` annotation.

    No ``.order_by`` — ``paginated_list_response`` applies the total ordering itself,
    so the per-entity sort lives in the ``list_ordering`` passed to
    ``register_taxonomy_router``. Parity of the annotation against the Python
    ``bulk_title_counts_via_models`` helper is pinned in ``test_api_catalog_list``."""
    return model_cls.objects.active().annotate(title_count=_flat_taxonomy_title_count())


def _taxonomy_detail_qs(model_class: type[_TaxM]) -> QuerySet[_TaxM]:  # noqa: UP047
    # The single claims Prefetch sits alongside relation-name strings ("aliases"),
    # so the list is widened to the ``str | Prefetch`` union; the Prefetch type args
    # are erased to match the sibling ``_detail_qs`` helpers.
    prefetches: list[str | Prefetch[Any, Any, Any]] = [claims_prefetch()]
    if model_class is RewardType:
        prefetches.append("aliases")
    return model_class.objects.active().prefetch_related(*prefetches)


def _patch_taxonomy(  # noqa: UP047
    request: HttpRequest,
    model_class: type[_TaxM],
    public_id: str,
    data: ClaimPatchSchema,
) -> TaxonomySchema:
    """Shared PATCH handler for all taxonomy entities.

    Each calling route is decorated with ``@rate_limited(EDIT_RATE_LIMIT_SPEC)``
    — keeping the bucket charge on the public route (not in this helper)
    so the inventory walker can read the marker off ``op.view_func``.
    """
    obj = get_object_or_404(
        model_class.objects.active(), **{model_class.public_id_field: public_id}
    )
    specs = plan_scalar_field_claims(
        model_class, data.fields, entity=obj, inline_citations=data.inline_citations
    )

    execute_claims(
        obj,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
    )

    obj = get_object_or_404(_taxonomy_detail_qs(model_class), slug=obj.slug)
    return _serialize_taxonomy(obj)


def _register_delete_restore(  # noqa: UP047
    router: Router,
    model_cls: type[_TaxM],
    *,
    child_related_name: str | None = None,
    parent_field: str | None = None,
) -> None:
    """Thin wrapper — auto-plumbs the standard taxonomy detail/serialize pair."""

    def detail_qs() -> QuerySet[_TaxM]:
        return _taxonomy_detail_qs(model_cls)

    register_entity_delete_restore(
        router,
        model_cls,
        detail_qs=detail_qs,
        serialize_detail=_serialize_taxonomy,
        response_schema=TaxonomySchema,
        child_related_name=child_related_name,
        parent_field=parent_field,
    )


def _register_create(  # noqa: UP047
    router: Router,
    model_cls: type[_TaxM],
    *,
    parent_field: str | None = None,
    parent_model: type[CatalogModel] | None = None,
    route_suffix: str = "",
) -> None:
    def detail_qs() -> QuerySet[_TaxM]:
        return _taxonomy_detail_qs(model_cls)

    register_entity_create(
        router,
        model_cls,
        detail_qs=detail_qs,
        serialize_detail=_serialize_taxonomy,
        response_schema=TaxonomySchema,
        parent_field=parent_field,
        parent_model=parent_model,
        route_suffix=route_suffix,
    )


def register_taxonomy_router(  # noqa: UP047
    router: Router,
    model_cls: type[_FlatTaxM],
    *,
    list_ordering: tuple[str, ...],
    list_schema: type[_TaxonomyListPage],
) -> None:
    """Wire a flat title-count taxonomy's whole router surface in one call.

    Collapses the per-entity boilerplate that cabinets / tags / game-formats
    used to repeat: the paginated ``GET /`` list, the ``PATCH
    /{public_id}/claims/`` edit, plus create and delete/restore (delegated to
    the shared ``_register_create`` / ``_register_delete_restore`` registrars).

    The one real per-entity variation is *list_ordering* — a **total** order
    (append ``pk``): popularity ``("-title_count", "name", "pk")`` for
    cabinets / tags vs editorial ``("display_order", "name", "pk")`` for
    game-formats. *list_schema* is the entity's own ``{items, count}`` page
    wrapper, passed so each keeps its named OpenAPI component.

    Inner handlers are annotated with module-global types only: this module
    uses ``from __future__ import annotations``, so Ninja's ``get_type_hints``
    would fail to resolve a function-scoped TypeVar in a view annotation.
    """
    ordering_note = (
        "Ordered by title count, then alphabetically."
        if list_ordering[0] == "-title_count"
        else "In curated order."
    )

    def _list(
        request: HttpRequest, q: NameQuery = "", page: PageParam = 1
    ) -> _TaxonomyListPage:
        result = paginated_list_response(
            _flat_taxonomy_list_qs(model_cls),
            q=q,
            ordering=list_ordering,
            page=page,
            serialize_row=_serialize_taxonomy_with_count,
        )
        return list_schema(items=result.items, count=result.total)

    # ``__name__`` is the view-function name Ninja derives the OpenAPI operationId
    # and summary from, and ``__doc__`` becomes the operation description.
    # Reproduce the entities' hand-written ``list_<plural>`` / ``patch_<entity>``
    # names and descriptions so converted entities keep byte-identical operation
    # metadata — and stay consistent with the not-yet-converted ones.
    _list.__name__ = f"list_{model_cls.entity_type_plural.replace('-', '_')}"
    _list.__doc__ = (
        f"{model_cls.entity_type_plural.replace('-', ' ').capitalize()}, paginated. "
        f"Search with ``q``. {ordering_note}"
    )
    router.get("/", response=list_schema)(_list)

    def _patch(
        request: HttpRequest, public_id: str, data: ClaimPatchSchema
    ) -> TaxonomySchema:
        return _patch_taxonomy(request, model_cls, public_id, data)

    _patch.__name__ = f"patch_{model_cls.entity_type.replace('-', '_')}"
    _patch = requires(Activity.CATALOG_EDIT)(rate_limited(EDIT_RATE_LIMIT_SPEC)(_patch))
    router.patch(
        "/{path:public_id}/claims/",
        auth=django_auth,
        response={
            200: TaxonomySchema,
            422: ValidationErrorSchema,
            429: RateLimitErrorSchema,
        },
        tags=["private"],
    )(_patch)

    _register_create(router, model_cls)
    _register_delete_restore(router, model_cls)


# ---------------------------------------------------------------------------
# Technology Generations router
# ---------------------------------------------------------------------------

technology_generations_router = Router(tags=["technology-generations"])


@technology_generations_router.get(
    "/", response=list[TechnologyGenerationListItemSchema]
)
@decorate_view(cache_control(no_cache=True))
def list_technology_generations(
    request: HttpRequest,
) -> list[TechnologyGenerationListItemSchema]:
    """Every technology generation with its subgenerations, in curated order."""
    gens = list(TechnologyGeneration.objects.active())
    subgens = list(TechnologySubgeneration.objects.active())

    gen_counts = bulk_title_counts_via_models(
        [g.pk for g in gens], "technology_generation"
    )
    subgen_counts = _bulk_title_counts_for_subgenerations([s.pk for s in subgens])

    subgens_by_gen: dict[int, list[TechnologySubgeneration]] = {}
    for s in subgens:
        subgens_by_gen.setdefault(s.technology_generation_id, []).append(s)
    for group in subgens_by_gen.values():
        group.sort(key=lambda s: (s.display_order, s.name.lower()))

    gens.sort(key=lambda g: (g.display_order, g.name.lower()))

    return [
        TechnologyGenerationListItemSchema(
            **_serialize_taxonomy(g).model_dump(),
            title_count=gen_counts.get(g.pk, 0),
            subgenerations=[
                TaxonomyWithTitleCountSchema(
                    **_serialize_taxonomy(s).model_dump(),
                    title_count=subgen_counts.get(s.pk, 0),
                )
                for s in subgens_by_gen.get(g.pk, [])
            ],
        )
        for g in gens
    ]


def _bulk_title_counts_for_subgenerations(
    subgen_pks: list[int],
) -> dict[int, int]:
    """Count titles under each subgeneration, mirroring the OR semantics
    of the ``/api/models/?subgeneration=...`` filter: a machine counts
    toward a subgen if its own FK references it OR its ``system``'s FK
    references it. Without the inherited branch, subgens whose machines
    carry the attribution only through ``system`` show ``0 titles`` while
    the detail page lists many — see ``machine_models._build_model_list_qs``.
    """
    if not subgen_pks:
        return {}

    base = (
        MachineModel.objects.active()
        .filter(variant_of__isnull=True)
        .filter(active_status_q("title"))
    )
    direct = base.filter(technology_subgeneration__in=subgen_pks).values_list(
        "technology_subgeneration_id", "title_id"
    )
    inherited = base.filter(
        system__technology_subgeneration__in=subgen_pks
    ).values_list("system__technology_subgeneration_id", "title_id")

    titles_by_subgen: dict[int, set[int]] = {}
    for sg_id, title_id in chain(direct, inherited):
        if sg_id is None or title_id is None:
            continue
        titles_by_subgen.setdefault(sg_id, set()).add(title_id)

    return {pk: len(titles_by_subgen.get(pk, ())) for pk in subgen_pks}


@technology_generations_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: TaxonomySchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_technology_generation(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, TechnologyGeneration, public_id, data)


# ---------------------------------------------------------------------------
# Display Types router
# ---------------------------------------------------------------------------

display_types_router = Router(tags=["display-types"])


@display_types_router.get("/", response=list[DisplayTypeListItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_display_types(request: HttpRequest) -> list[DisplayTypeListItemSchema]:
    """Every display type with its subtypes, in curated order."""
    types = list(DisplayType.objects.active())
    subtypes = list(DisplaySubtype.objects.active())

    type_counts = bulk_title_counts_via_models([t.pk for t in types], "display_type")
    subtype_counts = bulk_title_counts_via_models(
        [s.pk for s in subtypes], "display_subtype"
    )

    subtypes_by_type: dict[int, list[DisplaySubtype]] = {}
    for s in subtypes:
        subtypes_by_type.setdefault(s.display_type_id, []).append(s)
    for group in subtypes_by_type.values():
        group.sort(key=lambda s: (s.display_order, s.name.lower()))

    types.sort(key=lambda t: (t.display_order, t.name.lower()))

    return [
        DisplayTypeListItemSchema(
            **_serialize_taxonomy(t).model_dump(),
            title_count=type_counts.get(t.pk, 0),
            subtypes=[
                TaxonomyWithTitleCountSchema(
                    **_serialize_taxonomy(s).model_dump(),
                    title_count=subtype_counts.get(s.pk, 0),
                )
                for s in subtypes_by_type.get(t.pk, [])
            ],
        )
        for t in types
    ]


@display_types_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: TaxonomySchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_display_type(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, DisplayType, public_id, data)


# ---------------------------------------------------------------------------
# Technology Subgenerations router
# ---------------------------------------------------------------------------

technology_subgenerations_router = Router(tags=["technology-subgenerations"])


@technology_subgenerations_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: TaxonomySchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_technology_subgeneration(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, TechnologySubgeneration, public_id, data)


# ---------------------------------------------------------------------------
# Display Subtypes router
# ---------------------------------------------------------------------------

display_subtypes_router = Router(tags=["display-subtypes"])


@display_subtypes_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: TaxonomySchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_display_subtype(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, DisplaySubtype, public_id, data)


# ---------------------------------------------------------------------------
# Cabinets router
# ---------------------------------------------------------------------------

cabinets_router = Router(tags=["cabinets"])


class CabinetListSchema(_TaxonomyListPage):
    """A page of cabinets: ``items`` holds this page's rows; ``count`` is the total
    number of matching cabinets across all pages."""


# Cabinets — popularity-ordered. The factory wires list + patch + create +
# delete/restore; see ``register_taxonomy_router``.
register_taxonomy_router(
    cabinets_router,
    Cabinet,
    list_ordering=("-title_count", "name", "pk"),
    list_schema=CabinetListSchema,
)


# ---------------------------------------------------------------------------
# Game Formats router
# ---------------------------------------------------------------------------

game_formats_router = Router(tags=["game-formats"])


class GameFormatListSchema(_TaxonomyListPage):
    """A page of game formats: ``items`` holds this page's rows; ``count`` is the
    total number of matching game formats across all pages."""


# Game formats — editorial ``display_order`` sort (chronologically meaningful),
# unlike the popularity-sorted cabinets/tags.
register_taxonomy_router(
    game_formats_router,
    GameFormat,
    list_ordering=("display_order", "name", "pk"),
    list_schema=GameFormatListSchema,
)


# ---------------------------------------------------------------------------
# Production Statuses router
# ---------------------------------------------------------------------------

production_statuses_router = Router(tags=["production-statuses"])


class ProductionStatusListSchema(_TaxonomyListPage):
    """A page of production statuses: ``items`` holds this page's rows; ``count``
    is the total number of matching production statuses across all pages."""


# Production statuses — editorial ``display_order`` sort (announced → produced →
# unreleased → one-off), like game formats.
register_taxonomy_router(
    production_statuses_router,
    ProductionStatus,
    list_ordering=("display_order", "name", "pk"),
    list_schema=ProductionStatusListSchema,
)


# ---------------------------------------------------------------------------
# Reward Types router
# ---------------------------------------------------------------------------


class RewardTypeDetailSchema(TaxonomySchema):
    """The reward-type record — the response of the mutation endpoints. The
    read-only detail page's payload is :class:`RewardTypeDetailPageSchema`."""


class RewardTypeDetailPageSchema(RewardTypeDetailSchema):
    games: GameListSchema


reward_types_router = Router(tags=["reward-types"])


def _reward_type_detail_qs() -> QuerySet[RewardType]:
    return RewardType.objects.active().prefetch_related("aliases", claims_prefetch())


def _serialize_reward_type_detail(rt: RewardType) -> RewardTypeDetailSchema:
    return RewardTypeDetailSchema(**_serialize_taxonomy(rt).model_dump())


class RewardTypeListSchema(Schema):
    """A page of reward types: ``items`` holds this page's rows; ``count`` is the
    total number of matching reward types across all pages."""

    items: list[TaxonomyWithTitleCountSchema]
    count: int


def _reward_type_list_qs() -> QuerySet[RewardType]:
    # RewardType is the one flat taxonomy with an ``aliases`` relation the row
    # serializer reads — prefetch it to avoid an N+1 over the page.
    return (
        RewardType.objects.active()
        .annotate(title_count=_flat_taxonomy_title_count())
        .prefetch_related("aliases")
        .order_by("-title_count", "name")
    )


@reward_types_router.get("/", response=RewardTypeListSchema)
def list_reward_types(
    request: HttpRequest, q: NameAliasQuery = "", page: PageParam = 1
) -> RewardTypeListSchema:
    """Reward types, paginated. Search with ``q``. Ordered by title count, then
    alphabetically."""
    result = paginated_list_response(
        _reward_type_list_qs(),
        q=q,
        ordering=("-title_count", "name", "pk"),
        page=page,
        serialize_row=_serialize_taxonomy_with_count,
    )
    return RewardTypeListSchema(items=result.items, count=result.total)


@reward_types_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: RewardTypeDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_reward_type(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> RewardTypeDetailSchema:
    obj = get_object_or_404(
        RewardType.objects.active(), **{RewardType.public_id_field: public_id}
    )
    specs = plan_scalar_field_claims(
        RewardType, data.fields, entity=obj, inline_citations=data.inline_citations
    )

    execute_claims(
        obj,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
    )

    rt = get_object_or_404(_reward_type_detail_qs(), slug=obj.slug)
    return _serialize_reward_type_detail(rt)


# ---------------------------------------------------------------------------
# Tags router
# ---------------------------------------------------------------------------

tags_router = Router(tags=["tags"])


class TagListSchema(_TaxonomyListPage):
    """A page of tags: ``items`` holds this page's rows; ``count`` is the total
    number of matching tags across all pages."""


# Tags — popularity-ordered.
register_taxonomy_router(
    tags_router,
    Tag,
    list_ordering=("-title_count", "name", "pk"),
    list_schema=TagListSchema,
)


# ---------------------------------------------------------------------------
# Credit Roles router
# ---------------------------------------------------------------------------


class CreditRoleDetailSchema(TaxonomySchema):
    """A credit role plus the people credited in it."""

    people: list[PersonCardSchema] = Field(
        [], description="People credited in this role."
    )


credit_roles_router = Router(tags=["credit-roles"])


def _credit_role_people(cr: CreditRole) -> list[PersonCardSchema]:
    """Rank Persons by distinct active Titles credited in *cr*.

    Titles roll up all MachineModels (parent + variants) so a person credited
    only on an LE/Pro/Premium still counts toward the title exactly once.
    Series credits are intentionally excluded from the public rendering; the
    delete-blocker path covers series via ``soft_delete_usage_blockers``.

    Implemented Credit-side and then fanned out to Person so the SQL stays
    legible — the Person-side equivalent needs matching ``filter=`` subclauses
    on outer and annotation scopes, and tends to drift.
    """
    ranked = list(
        Credit.objects.filter(
            role=cr,
            model__isnull=False,
        )
        .filter(active_status_q("model"))
        .filter(active_status_q("model__title"))
        .filter(active_status_q("person"))
        .values("person")
        .annotate(credit_count=Count("model__title", distinct=True))
        .order_by("-credit_count")
    )
    if not ranked:
        return []

    # Preserve rank order while fetching Person rows with alias prefetch.
    person_ids = [r["person"] for r in ranked]
    count_by_id = {r["person"]: r["credit_count"] for r in ranked}
    people_by_id = {
        p.pk: p
        for p in Person.objects.filter(pk__in=person_ids).prefetch_related("aliases")
    }

    # Batch thumbnail per person — newest credited *active* model in this
    # role with extra_data. Active filters mirror the ranking query so a
    # person whose only active credit is on a low-profile machine doesn't
    # end up with a thumbnail from a deleted sibling.
    person_thumb_model: dict[int, int] = {}
    for person_id, model_id in (
        Credit.objects.filter(
            role=cr,
            person_id__in=person_ids,
            model__isnull=False,
            model__extra_data__isnull=False,
        )
        .filter(active_status_q("model"))
        .filter(active_status_q("model__title"))
        .order_by(F("model__year").desc(nulls_last=True))
        .values_list("person_id", "model_id")
    ):
        if person_id not in person_thumb_model:
            person_thumb_model[person_id] = model_id
    thumb_models = {
        m.pk: m
        for m in MachineModel.objects.filter(
            id__in=set(person_thumb_model.values())
        ).only("id", "extra_data")
    }
    thumb_media = fetch_model_media_map(person_thumb_model.values())

    min_rank = get_minimum_display_rank()
    out: list[PersonCardSchema] = []
    for pid in person_ids:
        person = people_by_id.get(pid)
        if person is None:
            continue
        thumbnail: str | None = None
        tm_id = person_thumb_model.get(pid)
        tm = thumb_models.get(tm_id) if tm_id else None
        if tm:
            t, _ = extract_image_urls(
                tm.extra_data or {}, thumb_media.get(tm.pk), min_rank=min_rank
            )
            if t:
                thumbnail = t
        out.append(
            PersonCardSchema(
                name=person.name,
                slug=person.slug,
                aliases=[a.value for a in person.aliases.all()],
                credit_count=count_by_id[pid],
                thumbnail_url=thumbnail,
            )
        )
    return out


def _credit_role_detail_qs() -> QuerySet[CreditRole]:
    # CreditRole has no alias relation — prefetch claims only.
    return CreditRole.objects.active().prefetch_related(claims_prefetch())


def _serialize_credit_role_detail(cr: CreditRole) -> CreditRoleDetailSchema:
    return CreditRoleDetailSchema(
        **_serialize_taxonomy(cr).model_dump(),
        people=_credit_role_people(cr),
    )


def _serialize_credit_role_detail_no_people(cr: CreditRole) -> CreditRoleDetailSchema:
    # Used by the create response: a just-created role has no credits yet,
    # so the aggregate query is guaranteed empty. Skip it.
    return CreditRoleDetailSchema(**_serialize_taxonomy(cr).model_dump(), people=[])


class CreditRoleListSchema(Schema):
    """A page of credit roles: ``items`` holds this page's rows; ``count`` is the
    total number of matching credit roles across all pages."""

    # No-per-row-count variant: rows are plain ``TaxonomySchema`` (no
    # ``title_count``), but the page still carries the pagination ``count``.
    items: list[TaxonomySchema]
    count: int


def _serialize_credit_role_row(
    cr: CreditRole, thumbnail: str | None = None
) -> TaxonomySchema:
    """Row serializer for the paginated credit-roles handler — the plain
    ``TaxonomySchema`` body, no count. ``thumbnail`` is unused (credit roles carry no
    image) but accepted to satisfy the core's ``RowSerializer`` signature."""
    return _serialize_taxonomy(cr)


@credit_roles_router.get("/", response=CreditRoleListSchema)
def list_credit_roles(
    request: HttpRequest, q: NameQuery = "", page: PageParam = 1
) -> CreditRoleListSchema:
    """Credit roles, paginated. Search with ``q``. Ordered alphabetically."""
    result = paginated_list_response(
        CreditRole.objects.active(),
        q=q,
        ordering=("name", "pk"),
        page=page,
        serialize_row=_serialize_credit_role_row,
    )
    return CreditRoleListSchema(items=result.items, count=result.total)


@credit_roles_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: CreditRoleDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_credit_role(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> CreditRoleDetailSchema:
    obj = get_object_or_404(
        CreditRole.objects.active(), **{CreditRole.public_id_field: public_id}
    )
    specs = plan_scalar_field_claims(
        CreditRole, data.fields, entity=obj, inline_citations=data.inline_citations
    )

    execute_claims(
        obj,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
    )

    cr = get_object_or_404(_credit_role_detail_qs(), slug=obj.slug)
    return _serialize_credit_role_detail(cr)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring — bespoke taxonomies only
# ---------------------------------------------------------------------------
#
# The flat title-count taxonomies (cabinets, game-formats, tags) self-wire
# their whole surface — list + patch + create + delete/restore — via
# ``register_taxonomy_router`` in their own sections above. What remains here
# is the population that *can't* ride that factory:
#
# * TechnologyGeneration / DisplayType — Python-side nested-hierarchy list
#   (rolls subgenerations / subtypes into the parent row), not a flat ``GET /``.
# * TechnologySubgeneration / DisplaySubtype — patch-only, no list endpoint.
# * RewardType — alias-aware list search + a bespoke detail schema (its
#   referencing machines), so its list and patch can't share the flat path.
# * CreditRole — no ``title_count``; a custom people-aggregation detail.
#
# These keep their hand-written handlers above and register their
# create + delete/restore explicitly below.

# Delete / restore / preview — every target entity on its own router.
_register_delete_restore(
    technology_generations_router,
    TechnologyGeneration,
    child_related_name="subgenerations",
)
_register_delete_restore(
    technology_subgenerations_router,
    TechnologySubgeneration,
    parent_field="technology_generation",
)
_register_delete_restore(
    display_types_router,
    DisplayType,
    child_related_name="subtypes",
)
_register_delete_restore(
    display_subtypes_router,
    DisplaySubtype,
    parent_field="display_type",
)
_register_delete_restore(reward_types_router, RewardType)
register_entity_delete_restore(
    credit_roles_router,
    CreditRole,
    detail_qs=_credit_role_detail_qs,
    serialize_detail=_serialize_credit_role_detail,
    response_schema=CreditRoleDetailSchema,
)


# Bespoke detail GET. Registered AFTER the factory and PATCH/claims routes so
# its greedy ``{path:public_id}`` doesn't shadow ``/{path:public_id}/claims/``,
# ``/{path:public_id}/delete-preview/``, etc. — Django's URL resolver picks
# the first matching pattern, so the more-specific routes have to come first.
@credit_roles_router.get("/{path:public_id}", response=CreditRoleDetailSchema)
@decorate_view(cache_control(no_cache=True))
def get_credit_role(
    request: HttpRequest,
    public_id: Annotated[
        str, PathParam(description="Credit-role slug (see `GET /api/credit-roles/`).")
    ],
) -> CreditRoleDetailSchema:
    """A single credit role by its slug."""
    return _serialize_credit_role_detail(
        get_object_or_404(
            _credit_role_detail_qs(), **{CreditRole.public_id_field: public_id}
        )
    )


# Create — parentless entities on their own router.
_register_create(technology_generations_router, TechnologyGeneration)
_register_create(display_types_router, DisplayType)
_register_create(reward_types_router, RewardType)
register_entity_create(
    credit_roles_router,
    CreditRole,
    detail_qs=_credit_role_detail_qs,
    serialize_detail=_serialize_credit_role_detail_no_people,
    response_schema=CreditRoleDetailSchema,
)

# Create — parented entities nested under the parent's router.
_register_create(
    technology_generations_router,
    TechnologySubgeneration,
    parent_field="technology_generation",
    parent_model=TechnologyGeneration,
    route_suffix="subgenerations",
)
_register_create(
    display_types_router,
    DisplaySubtype,
    parent_field="display_type",
    parent_model=DisplayType,
    route_suffix="subtypes",
)
