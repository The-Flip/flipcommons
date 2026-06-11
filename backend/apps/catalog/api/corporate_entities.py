"""Corporate entities router — list, detail, and claims endpoints."""

from __future__ import annotations

from typing import cast

from django.db.models import Count, F, Max, Min, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.security import django_auth
from pydantic import Field

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
    OperatingStatus,
)
from ._typing import CorporateEntityListAnnotations
from .constants import NameAliasQuery, PageParam
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
    model_year_bounds,
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
    """A corporate entity in list results."""

    name: str = Field(description="The corporate entity's display name.")
    slug: str = Field(description="The corporate entity's URL slug.")
    manufacturer: EntityRef = Field(
        description="The manufacturer this corporate entity belongs to."
    )
    year_of_first_model: int | None = Field(
        None, description="Earliest model year for this corporate entity."
    )
    year_of_last_model: int | None = Field(
        None, description="Latest model year for this corporate entity."
    )
    operating_status: OperatingStatus = Field(
        OperatingStatus.UNKNOWN,
        description="Whether this corporate entity is still producing pinball.",
    )
    model_count: int = Field(
        0, description="Number of machine models from this corporate entity."
    )
    locations: list[CorporateEntityLocationSchema] = Field(
        [], description="Locations associated with this corporate entity."
    )


class CorporateEntityListSchema(Schema):
    """A page of corporate entities: ``items`` holds this page's rows; ``count`` is
    the total number of matching corporate entities across all pages."""

    items: list[CorporateEntityListItemSchema]
    count: int


class CorporateEntityDetailSchema(CatalogDetailSchema):
    slug: str
    manufacturer: EntityRef
    year_of_first_model: int | None = None
    year_of_last_model: int | None = None
    operating_status: OperatingStatus = OperatingStatus.UNKNOWN
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
    bounds = model_year_bounds(ce.models.all())
    return CorporateEntityDetailSchema(
        name=ce.name,
        public_id=ce.public_id,
        last_modified=ce.last_modified,
        slug=ce.slug,
        description=describe(ce),
        manufacturer=EntityRef(
            name=ce.manufacturer.name, public_id=ce.manufacturer.public_id
        ),
        year_of_first_model=bounds.first,
        year_of_last_model=bounds.last,
        operating_status=OperatingStatus(ce.operating_status),
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
    nonvariant = Q(models__variant_of__isnull=True) & active_status_q("models")
    return (
        CorporateEntity.objects.active()
        .select_related("manufacturer")
        .annotate(
            model_count=Count("models", filter=nonvariant),
            year_of_first_model=Min("models__year", filter=nonvariant),
            year_of_last_model=Max("models__year", filter=nonvariant),
        )
        .prefetch_related(
            Prefetch(
                "locations",
                queryset=CorporateEntityLocation.objects.select_related(
                    "location__parent__parent__parent"
                ),
            ),
        )
        .order_by("manufacturer__name", "year_of_first_model")
    )


def _serialize_corporate_entity_row(
    ce: CorporateEntity, thumbnail: str | None = None
) -> CorporateEntityListItemSchema:
    row = cast(CorporateEntityListAnnotations, ce)
    return CorporateEntityListItemSchema(
        name=ce.name,
        slug=ce.slug,
        manufacturer=EntityRef(
            name=ce.manufacturer.name, public_id=ce.manufacturer.public_id
        ),
        year_of_first_model=row.year_of_first_model,
        year_of_last_model=row.year_of_last_model,
        operating_status=OperatingStatus(ce.operating_status),
        model_count=row.model_count,
        locations=serialize_locations(ce),
    )


@corporate_entities_router.get("/", response=CorporateEntityListSchema)
def list_corporate_entities(
    request: HttpRequest, q: NameAliasQuery = "", page: PageParam = 1
) -> CorporateEntityListSchema:
    """Corporate entities, paginated. Search with ``q``. Ordered by manufacturer,
    then earliest model year."""
    result = paginated_list_response(
        _corporate_entity_list_qs(),
        q=q,
        ordering=("manufacturer__name", "year_of_first_model", "pk"),
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
