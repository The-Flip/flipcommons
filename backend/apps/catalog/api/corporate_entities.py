"""Corporate entities router — list, detail, and claims endpoints."""

from __future__ import annotations

from typing import cast

from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.security import django_auth

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..models import (
    CatalogModel,
    CorporateEntity,
    CorporateEntityLocation,
    MachineModel,
    Manufacturer,
)
from ._typing import HasModelCount
from .edit_claims import (
    execute_claims,
    plan_alias_claims,
    raise_form_error,
    validate_scalar_fields,
)
from .entity_crud import register_entity_create, register_entity_delete_restore
from .entity_list import paginated_list_response
from .helpers import (
    collect_titles,
    serialize_locations,
)
from .manufacturers import manufacturers_router
from .rich_text import describe
from .schemas import (
    CatalogDetailSchema,
    CorporateEntityClaimPatchSchema,
    CorporateEntityLocationSchema,
    EntityCreateInputSchema,
    EntityRef,
    RelatedTitleSchema,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CorporateEntityListItemSchema(Schema):
    name: str
    slug: str
    manufacturer: EntityRef
    year_start: int | None = None
    year_end: int | None = None
    model_count: int = 0
    locations: list[CorporateEntityLocationSchema] = []


class CorporateEntityListSchema(Schema):
    """``{items, count}`` page of corporate entities — the wire shape
    ``createPaginatedLoader`` expects (it derives has_more from items.length < count)."""

    items: list[CorporateEntityListItemSchema]
    count: int


class CorporateEntityDetailSchema(CatalogDetailSchema):
    slug: str
    manufacturer: EntityRef
    year_start: int | None = None
    year_end: int | None = None
    ipdb_manufacturer_id: int | None = None
    aliases: list[str] = []
    locations: list[CorporateEntityLocationSchema] = []
    titles: list[RelatedTitleSchema]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail_qs() -> QuerySet[CorporateEntity]:
    return (
        CorporateEntity.objects.active()
        .select_related("manufacturer")
        .prefetch_related(
            "aliases",
            Prefetch(
                "locations",
                queryset=CorporateEntityLocation.objects.select_related(
                    "location__parent__parent__parent"
                ),
            ),
            Prefetch(
                "models",
                queryset=MachineModel.objects.active()
                .filter(variant_of__isnull=True)
                .select_related("technology_generation", "title")
                .order_by(F("year").desc(nulls_last=True), "name"),
            ),
            claims_prefetch(),
        )
    )


def _serialize_detail(ce: CorporateEntity) -> CorporateEntityDetailSchema:
    return CorporateEntityDetailSchema(
        name=ce.name,
        public_id=ce.public_id,
        last_modified=ce.last_modified,
        slug=ce.slug,
        description=describe(ce),
        manufacturer=EntityRef(
            name=ce.manufacturer.name, public_id=ce.manufacturer.public_id
        ),
        year_start=ce.year_start,
        year_end=ce.year_end,
        ipdb_manufacturer_id=ce.ipdb_manufacturer_id,
        aliases=[a.value for a in ce.aliases.all()],
        locations=serialize_locations(ce),
        titles=collect_titles(ce.models.all()),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

corporate_entities_router = Router(tags=["corporate-entities"])


def _corporate_entity_list_qs() -> QuerySet[CorporateEntity]:
    return (
        CorporateEntity.objects.active()
        .select_related("manufacturer")
        .annotate(
            model_count=Count(
                "models",
                filter=Q(models__variant_of__isnull=True) & active_status_q("models"),
            )
        )
        .prefetch_related(
            Prefetch(
                "locations",
                queryset=CorporateEntityLocation.objects.select_related(
                    "location__parent__parent__parent"
                ),
            ),
        )
        .order_by("manufacturer__name", "year_start")
    )


def _serialize_corporate_entity_row(
    ce: CorporateEntity, thumbnail: str | None = None
) -> CorporateEntityListItemSchema:
    return CorporateEntityListItemSchema(
        name=ce.name,
        slug=ce.slug,
        manufacturer=EntityRef(
            name=ce.manufacturer.name, public_id=ce.manufacturer.public_id
        ),
        year_start=ce.year_start,
        year_end=ce.year_end,
        model_count=cast(HasModelCount, ce).model_count,
        locations=serialize_locations(ce),
    )


@corporate_entities_router.get("/", response=CorporateEntityListSchema)
def list_corporate_entities(
    request: HttpRequest, q: str = "", page: int = 1
) -> CorporateEntityListSchema:
    """One page of corporate entities, by manufacturer then founding year, filtered
    server-side by ``q`` (name or alias)."""
    result = paginated_list_response(
        _corporate_entity_list_qs(),
        q=q,
        ordering=("manufacturer__name", "year_start", "pk"),
        page=page,
        serialize_row=_serialize_corporate_entity_row,
    )
    return CorporateEntityListSchema(items=result.items, count=result.total)


@corporate_entities_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: CorporateEntityDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_corporate_entity_claims(
    request: HttpRequest, public_id: str, data: CorporateEntityClaimPatchSchema
) -> CorporateEntityDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    if not data.fields and data.aliases is None:
        raise_form_error("No changes provided.")

    ce = get_object_or_404(
        CorporateEntity.objects.active(), **{CorporateEntity.public_id_field: public_id}
    )

    specs = validate_scalar_fields(CorporateEntity, data.fields, entity=ce)

    if data.aliases is not None:
        specs.extend(
            plan_alias_claims(
                ce,
                data.aliases,
                claim_field_name="corporate_entity_alias",
            )
        )

    if not specs:
        raise_form_error("No changes provided.")

    execute_claims(ce, specs, user=request.user, note=data.note, citation=data.citation)

    ce = get_object_or_404(_detail_qs(), slug=ce.slug)
    return _serialize_detail(ce)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------


def _scope_by_manufacturer(
    _data: EntityCreateInputSchema, parent: CatalogModel | None
) -> Q:
    # CE create is parented; the factory always passes a resolved parent.
    assert parent is not None
    return Q(manufacturer_id=parent.pk)


# Create is parented: ``POST /api/manufacturers/{parent_public_id}/corporate-entities/``
# mounted on the manufacturer router. Name collisions are scoped per parent —
# two manufacturers may each own a corporate entity with the same name, but
# not the same manufacturer.
register_entity_create(
    manufacturers_router,
    CorporateEntity,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_detail,
    response_schema=CorporateEntityDetailSchema,
    parent_field="manufacturer",
    parent_model=Manufacturer,
    route_suffix="corporate-entities",
    scope_filter_builder=_scope_by_manufacturer,
)
register_entity_delete_restore(
    corporate_entities_router,
    CorporateEntity,
    detail_qs=_detail_qs,
    serialize_detail=_serialize_detail,
    response_schema=CorporateEntityDetailSchema,
    parent_field="manufacturer",
)
