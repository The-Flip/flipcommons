"""Franchises router — list, detail, and claims endpoints."""

from __future__ import annotations

from typing import cast

from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.security import django_auth
from pydantic import Field

from apps.catalog.engine.rich_text import describe
from apps.claim_edit.claim_write import execute_claims, plan_scalar_field_claims
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited

from ..engine.entity_api.create import register_entity_create
from ..engine.entity_api.delete import register_entity_delete_restore
from ..engine.entity_api.listing import paginated_list_response
from ..engine.query.constants import NameQuery, PageParam
from ..models import Franchise
from ._typing import HasTitleCount
from .games import GameListSchema
from .schemas import ClaimPatchSchema, EntityDetailSchema

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FranchiseListItemSchema(Schema):
    """A franchise in list results."""

    name: str = Field(description="The franchise's display name.")
    slug: str = Field(description="The franchise's URL slug.")
    title_count: int = Field(0, description="Number of titles in this franchise.")


class FranchiseListSchema(Schema):
    """A page of franchises: ``items`` holds this page's rows; ``count`` is the total
    number of matching franchises across all pages."""

    items: list[FranchiseListItemSchema]
    count: int


class FranchiseDetailSchema(EntityDetailSchema):
    """The franchise record — the response of the mutation endpoints. The
    read-only detail page's payload is :class:`FranchiseDetailPageSchema`."""

    slug: str


class FranchiseDetailPageSchema(FranchiseDetailSchema):
    """The detail-page payload: the record plus page 1 of its games — the
    listing pinned to ``franchise=<slug>`` (a Title-only dimension, so the
    cards stay Titles) in the listing's defined order."""

    games: GameListSchema


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

franchises_router = Router()


def _franchise_list_qs() -> QuerySet[Franchise]:
    """Active franchises annotated with their active-title count, ordered most-titled
    first, then by name."""
    return (
        Franchise.objects.active()
        .annotate(title_count=Count("titles", filter=active_status_q("titles")))
        .order_by("-title_count", "name")
    )


def _serialize_franchise_row(
    franchise: Franchise, thumbnail: str | None = None
) -> FranchiseListItemSchema:
    return FranchiseListItemSchema(
        name=franchise.name,
        slug=franchise.slug,
        title_count=cast(HasTitleCount, franchise).title_count,
    )


@franchises_router.get("/", response=FranchiseListSchema)
def list_franchises(
    request: HttpRequest, q: NameQuery = "", page: PageParam = 1
) -> FranchiseListSchema:
    """Franchises, paginated. Search with ``q``. Ordered by title count, then
    alphabetically."""
    result = paginated_list_response(
        _franchise_list_qs(),
        q=q,
        ordering=("-title_count", "name", "pk"),
        page=page,
        serialize_row=_serialize_franchise_row,
    )
    return FranchiseListSchema(items=result.items, count=result.total)


def _franchise_detail_qs() -> QuerySet[Franchise]:
    return Franchise.objects.active().prefetch_related(claims_prefetch())


def _serialize_franchise_detail(franchise: Franchise) -> FranchiseDetailSchema:
    return FranchiseDetailSchema(
        name=franchise.name,
        public_id=franchise.public_id,
        last_modified=franchise.last_modified,
        slug=franchise.slug,
        description=describe(franchise),
    )


@franchises_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: FranchiseDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_franchise_claims(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> FranchiseDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    franchise = get_object_or_404(
        Franchise.objects.active(), **{Franchise.public_id_field: public_id}
    )
    specs = plan_scalar_field_claims(
        Franchise, data.fields, entity=franchise, inline_citations=data.inline_citations
    )

    execute_claims(
        franchise,
        specs,
        user=request.user,
        note=data.note,
        citations=data.citations,
        inline_citations=data.inline_citations,
    )

    franchise = get_object_or_404(_franchise_detail_qs(), slug=franchise.slug)
    return _serialize_franchise_detail(franchise)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------

register_entity_create(
    franchises_router,
    Franchise,
    detail_qs=_franchise_detail_qs,
    serialize_detail=_serialize_franchise_detail,
    response_schema=FranchiseDetailSchema,
)
register_entity_delete_restore(
    franchises_router,
    Franchise,
    detail_qs=_franchise_detail_qs,
    serialize_detail=_serialize_franchise_detail,
    response_schema=FranchiseDetailSchema,
)
