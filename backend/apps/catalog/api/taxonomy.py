"""Taxonomy routers — technology generations, display types, and related lookups."""

from __future__ import annotations

from itertools import chain
from typing import Any, TypeVar, cast

from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.security import django_auth

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

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
    RewardType,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
)
from ._counts import bulk_title_counts_via_models
from ._typing import HasTitleCount
from .edit_claims import execute_claims, plan_scalar_field_claims
from .entity_crud import (
    register_entity_create,
    register_entity_delete_restore,
)
from .entity_list import paginated_list_response
from .helpers import serialize_title_machine
from .images import extract_image_urls, fetch_model_media_map
from .people import PersonCardSchema
from .rich_text import build_rich_text
from .schemas import (
    CatalogDetailSchema,
    ClaimPatchSchema,
    TitleModelSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaxonomySchema(CatalogDetailSchema):
    slug: str
    display_order: int
    aliases: list[str] = []


class TaxonomyWithTitleCountSchema(TaxonomySchema):
    title_count: int = 0


class DisplayTypeListItemSchema(TaxonomyWithTitleCountSchema):
    subtypes: list[TaxonomyWithTitleCountSchema] = []


class TechnologyGenerationListItemSchema(TaxonomyWithTitleCountSchema):
    subgenerations: list[TaxonomyWithTitleCountSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Constrained TypeVar over the nine concrete taxonomy model classes that
# share ``TaxonomySchema`` as their public shape. Constraints (not a bound)
# are required so each call site binds ``_TaxM`` to the specific concrete
# class — otherwise `type[_TaxM]` collapses to the common base
# ``CatalogModel`` and ``.objects.active()`` / attribute access are lost.
# Written with ``typing.TypeVar`` rather than PEP 695 syntax so the nine
# constraints aren't repeated on every generic function; the per-def
# UP047 suppression below covers the associated ruff rule.
_TaxM = TypeVar(
    "_TaxM",
    Cabinet,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    GameFormat,
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
    obj: Cabinet | GameFormat | RewardType | Tag, thumbnail: str | None = None
) -> TaxonomyWithTitleCountSchema:
    """Row serializer for the paginated flat-taxonomy handlers: the shared
    ``TaxonomySchema`` body plus the ``title_count`` annotation read off the row.
    ``thumbnail`` is unused (these taxonomies carry no image) but is accepted to satisfy
    the core's ``RowSerializer`` signature."""
    return TaxonomyWithTitleCountSchema(
        **_serialize_taxonomy(obj).model_dump(),
        title_count=cast(HasTitleCount, obj).title_count,
    )


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
    specs = plan_scalar_field_claims(model_class, data.fields, entity=obj)

    execute_claims(
        obj, specs, user=request.user, note=data.note, citation=data.citation
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


class CabinetListSchema(Schema):
    """``{items, count}`` page of cabinets — the wire shape ``createPaginatedLoader``
    expects (it derives has_more from items.length < count)."""

    items: list[TaxonomyWithTitleCountSchema]
    count: int


def _cabinet_list_qs() -> QuerySet[Cabinet]:
    return (
        Cabinet.objects.active()
        .annotate(title_count=_flat_taxonomy_title_count())
        .order_by("-title_count", "name")
    )


@cabinets_router.get("/", response=CabinetListSchema)
def list_cabinets(
    request: HttpRequest, q: str = "", page: int = 1
) -> CabinetListSchema:
    """One page of cabinets, most-titled first, filtered server-side by ``q``."""
    result = paginated_list_response(
        _cabinet_list_qs(),
        q=q,
        ordering=("-title_count", "name", "pk"),
        page=page,
        serialize_row=_serialize_taxonomy_with_count,
    )
    return CabinetListSchema(items=result.items, count=result.total)


@cabinets_router.patch(
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
def patch_cabinet(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, Cabinet, public_id, data)


# ---------------------------------------------------------------------------
# Game Formats router
# ---------------------------------------------------------------------------

game_formats_router = Router(tags=["game-formats"])


class GameFormatListSchema(Schema):
    """``{items, count}`` page of game formats — the wire shape
    ``createPaginatedLoader`` expects (it derives has_more from items.length < count)."""

    items: list[TaxonomyWithTitleCountSchema]
    count: int


def _game_format_list_qs() -> QuerySet[GameFormat]:
    # Editorial ``display_order`` sort (chronologically meaningful), unlike the
    # popularity-sorted cabinets/tags; ``title_count`` is a display-only annotation here.
    return (
        GameFormat.objects.active()
        .annotate(title_count=_flat_taxonomy_title_count())
        .order_by("display_order", "name")
    )


@game_formats_router.get("/", response=GameFormatListSchema)
def list_game_formats(
    request: HttpRequest, q: str = "", page: int = 1
) -> GameFormatListSchema:
    """One page of game formats in editorial ``display_order``, filtered by ``q``."""
    result = paginated_list_response(
        _game_format_list_qs(),
        q=q,
        ordering=("display_order", "name", "pk"),
        page=page,
        serialize_row=_serialize_taxonomy_with_count,
    )
    return GameFormatListSchema(items=result.items, count=result.total)


@game_formats_router.patch(
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
def patch_game_format(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, GameFormat, public_id, data)


# ---------------------------------------------------------------------------
# Reward Types router
# ---------------------------------------------------------------------------


class RewardTypeDetailSchema(TaxonomySchema):
    machines: list[TitleModelSchema] = []


reward_types_router = Router(tags=["reward-types"])


def _reward_type_detail_qs() -> QuerySet[RewardType]:
    return RewardType.objects.active().prefetch_related(
        claims_prefetch(),
        Prefetch(
            "machine_models",
            queryset=MachineModel.objects.active()
            .filter(variant_of__isnull=True)
            .select_related("corporate_entity__manufacturer", "technology_generation")
            .order_by(F("year").desc(nulls_last=True), "name"),
        ),
    )


def _serialize_reward_type_detail(rt: RewardType) -> RewardTypeDetailSchema:
    min_rank = get_minimum_display_rank()
    machines_list = list(rt.machine_models.all())
    media_by_model = fetch_model_media_map(pm.pk for pm in machines_list)
    return RewardTypeDetailSchema(
        **_serialize_taxonomy(rt).model_dump(),
        machines=[
            serialize_title_machine(
                pm, min_rank=min_rank, media_by_model=media_by_model
            )
            for pm in machines_list
        ],
    )


class RewardTypeListSchema(Schema):
    """``{items, count}`` page of reward types — the wire shape
    ``createPaginatedLoader`` expects (it derives has_more from items.length < count)."""

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
    request: HttpRequest, q: str = "", page: int = 1
) -> RewardTypeListSchema:
    """One page of reward types, most-titled first, filtered by ``q`` (name or alias)."""
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
    specs = plan_scalar_field_claims(RewardType, data.fields, entity=obj)

    execute_claims(
        obj, specs, user=request.user, note=data.note, citation=data.citation
    )

    rt = get_object_or_404(_reward_type_detail_qs(), slug=obj.slug)
    return _serialize_reward_type_detail(rt)


# ---------------------------------------------------------------------------
# Tags router
# ---------------------------------------------------------------------------

tags_router = Router(tags=["tags"])


class TagListSchema(Schema):
    """``{items, count}`` page of tags — the wire shape ``createPaginatedLoader``
    expects (it derives has_more from items.length < count)."""

    items: list[TaxonomyWithTitleCountSchema]
    count: int


def _tag_list_qs() -> QuerySet[Tag]:
    return (
        Tag.objects.active()
        .annotate(title_count=_flat_taxonomy_title_count())
        .order_by("-title_count", "name")
    )


@tags_router.get("/", response=TagListSchema)
def list_tags(request: HttpRequest, q: str = "", page: int = 1) -> TagListSchema:
    """One page of tags, most-titled first, filtered server-side by ``q``."""
    result = paginated_list_response(
        _tag_list_qs(),
        q=q,
        ordering=("-title_count", "name", "pk"),
        page=page,
        serialize_row=_serialize_taxonomy_with_count,
    )
    return TagListSchema(items=result.items, count=result.total)


@tags_router.patch(
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
def patch_tag(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> TaxonomySchema:
    return _patch_taxonomy(request, Tag, public_id, data)


# ---------------------------------------------------------------------------
# Credit Roles router
# ---------------------------------------------------------------------------


class CreditRoleDetailSchema(TaxonomySchema):
    people: list[PersonCardSchema] = []


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
    """``{items, count}`` page of credit roles — the wire shape
    ``createPaginatedLoader`` expects. The no-per-row-count variant: rows carry no
    ``title_count`` badge (they're ``TaxonomySchema``), but the page still carries the
    pagination ``count`` the loader needs for has_more."""

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
    request: HttpRequest, q: str = "", page: int = 1
) -> CreditRoleListSchema:
    """One page of credit roles, alphabetical, filtered server-side by ``q``."""
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
    specs = plan_scalar_field_claims(CreditRole, data.fields, entity=obj)

    execute_claims(
        obj, specs, user=request.user, note=data.note, citation=data.citation
    )

    cr = get_object_or_404(_credit_role_detail_qs(), slug=obj.slug)
    return _serialize_credit_role_detail(cr)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------

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
_register_delete_restore(cabinets_router, Cabinet)
_register_delete_restore(game_formats_router, GameFormat)
_register_delete_restore(tags_router, Tag)
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
def get_credit_role(request: HttpRequest, public_id: str) -> CreditRoleDetailSchema:
    return _serialize_credit_role_detail(
        get_object_or_404(
            _credit_role_detail_qs(), **{CreditRole.public_id_field: public_id}
        )
    )


# Create — parentless entities on their own router.
_register_create(technology_generations_router, TechnologyGeneration)
_register_create(display_types_router, DisplayType)
_register_create(cabinets_router, Cabinet)
_register_create(game_formats_router, GameFormat)
_register_create(tags_router, Tag)
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
