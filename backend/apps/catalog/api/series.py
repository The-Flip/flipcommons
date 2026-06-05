"""Series router — list, detail, and claims endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from django.db.models import Count, F, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.security import django_auth

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.licensing import get_minimum_display_rank
from apps.core.models import active_status_q
from apps.core.schemas import RateLimitErrorSchema, ValidationErrorSchema
from apps.provenance.helpers import claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, rate_limited
from apps.provenance.schemas import RichTextSchema

from ..models import Credit, MachineModel, Series, Title
from ._typing import HasTitleCount
from .edit_claims import execute_claims, plan_scalar_field_claims
from .entity_crud import register_entity_create, register_entity_delete_restore
from .entity_list import paginated_list_response
from .helpers import (
    serialize_credit,
    serialize_title_ref,
)
from .images import extract_image_urls, fetch_model_media_map, fetch_title_media_map
from .rich_text import build_rich_text, describe
from .schemas import (
    CatalogDetailSchema,
    ClaimPatchSchema,
    CreditSchema,
    TitleRef,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SeriesListItemSchema(Schema):
    name: str
    slug: str
    description: RichTextSchema = RichTextSchema()
    title_count: int = 0
    thumbnail_url: str | None = None


class SeriesListSchema(Schema):
    """``{items, count}`` page of series — the wire shape ``createPaginatedLoader``
    expects (it derives has_more from items.length < count)."""

    items: list[SeriesListItemSchema]
    count: int


class SeriesDetailSchema(CatalogDetailSchema):
    slug: str
    titles: list[TitleRef]
    credits: list[CreditSchema] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _series_titles_qs() -> QuerySet[Title]:
    return (
        Title.objects.active()
        .annotate(
            model_count=Count(
                "machine_models",
                filter=Q(machine_models__variant_of__isnull=True)
                & active_status_q("machine_models"),
            )
        )
        .prefetch_related(
            "abbreviations",
            Prefetch(
                "machine_models",
                queryset=MachineModel.objects.active()
                .filter(variant_of__isnull=True)
                .select_related("corporate_entity__manufacturer")
                .order_by("year", "name"),
            ),
        )
    )


def _series_credits_qs() -> QuerySet[Credit]:
    return Credit.objects.filter(series__isnull=False).select_related("person", "role")


def _series_detail_qs() -> QuerySet[Series]:
    return Series.objects.active().prefetch_related(
        Prefetch("titles", queryset=_series_titles_qs()),
        Prefetch("credits", queryset=_series_credits_qs()),
        claims_prefetch(),
    )


def _serialize_series_detail(series: Series) -> SeriesDetailSchema:
    min_rank = get_minimum_display_rank()
    titles_list = list(series.titles.all())
    media_by_model = fetch_title_media_map(titles_list)
    return SeriesDetailSchema(
        name=series.name,
        public_id=series.public_id,
        last_modified=series.last_modified,
        slug=series.slug,
        description=describe(series),
        titles=[
            serialize_title_ref(t, min_rank=min_rank, media_by_model=media_by_model)
            for t in titles_list
        ],
        credits=[serialize_credit(c) for c in series.credits.all()],
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

series_router = Router(tags=["series"])


def _series_list_qs() -> QuerySet[Series]:
    """Active series annotated with their active-title count, ordered most-titled
    first, then by name."""
    return (
        Series.objects.active()
        .annotate(title_count=Count("titles", filter=active_status_q("titles")))
        .order_by("-title_count", "name")
    )


def _series_thumbnails(series_pks: Sequence[int]) -> dict[int, str | None]:
    """First image-bearing model per series (earliest year first), batched over
    *series_pks*.

    "Image-bearing" can't be expressed in SQL — uploaded ``EntityMedia`` lives in a
    separate relation and ``extra_data`` images are rank-gated — so we walk every
    active, non-variant model in year order and let ``extract_image_urls`` decide,
    taking the first that yields a thumbnail (uploaded media wins even when
    ``extra_data`` is empty). One ``values_list`` + one batched media fetch, no
    per-row queries.
    """
    if not series_pks:
        return {}
    min_rank = get_minimum_display_rank()
    rows = list(
        MachineModel.objects.active()
        .filter(variant_of__isnull=True, title__series__in=series_pks)
        .order_by(F("year").asc(nulls_last=True))
        .values_list("title__series", "id", "extra_data")
    )
    media_by_model = fetch_model_media_map(model_id for _, model_id, _ in rows)
    result: dict[int, str | None] = dict.fromkeys(series_pks, None)
    resolved: set[int] = set()
    for series_id, model_id, extra_data in rows:
        if series_id in resolved:
            continue
        thumb, _ = extract_image_urls(
            extra_data or {}, media_by_model.get(model_id), min_rank=min_rank
        )
        if thumb:
            result[series_id] = thumb
            resolved.add(series_id)
    return result


def _serialize_series_row(
    series: Series, thumbnail: str | None = None
) -> SeriesListItemSchema:
    return SeriesListItemSchema(
        name=series.name,
        slug=series.slug,
        description=build_rich_text(series, "description"),
        title_count=cast(HasTitleCount, series).title_count,
        thumbnail_url=thumbnail,
    )


@series_router.get("/", response=SeriesListSchema)
def list_series(request: HttpRequest, q: str = "", page: int = 1) -> SeriesListSchema:
    """One page of series (title count + thumbnail), most-titled first, filtered
    server-side by ``q``."""
    result = paginated_list_response(
        _series_list_qs(),
        q=q,
        ordering=("-title_count", "name", "pk"),
        page=page,
        serialize_row=_serialize_series_row,
        thumbnail_provider=_series_thumbnails,
    )
    return SeriesListSchema(items=result.items, count=result.total)


@series_router.patch(
    "/{path:public_id}/claims/",
    auth=django_auth,
    response={
        200: SeriesDetailSchema,
        422: ValidationErrorSchema,
        429: RateLimitErrorSchema,
    },
    tags=["private"],
)
@requires(Activity.CATALOG_EDIT)
@rate_limited(EDIT_RATE_LIMIT_SPEC)
def patch_series_claims(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> SeriesDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    series = get_object_or_404(
        Series.objects.active(), **{Series.public_id_field: public_id}
    )
    specs = plan_scalar_field_claims(Series, data.fields, entity=series)

    execute_claims(
        series, specs, user=request.user, note=data.note, citation=data.citation
    )

    series = get_object_or_404(_series_detail_qs(), slug=series.slug)
    return _serialize_series_detail(series)


# ---------------------------------------------------------------------------
# Create / delete / restore wiring
# ---------------------------------------------------------------------------

register_entity_create(
    series_router,
    Series,
    detail_qs=_series_detail_qs,
    serialize_detail=_serialize_series_detail,
    response_schema=SeriesDetailSchema,
)
register_entity_delete_restore(
    series_router,
    Series,
    detail_qs=_series_detail_qs,
    serialize_detail=_serialize_series_detail,
    response_schema=SeriesDetailSchema,
)
