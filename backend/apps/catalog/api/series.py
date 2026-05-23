"""Series router — list, detail, and claims endpoints."""

from __future__ import annotations

from typing import cast

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
from apps.provenance.helpers import active_claims, claims_prefetch
from apps.provenance.rate_limits import EDIT_RATE_LIMIT_SPEC, check_and_record
from apps.provenance.schemas import RichTextSchema

from ..models import Credit, MachineModel, Series, Title
from ._typing import HasTitleCount
from .edit_claims import execute_claims, plan_scalar_field_claims
from .entity_crud import register_entity_create, register_entity_delete_restore
from .helpers import (
    serialize_credit,
    serialize_title_ref,
)
from .images import extract_image_urls, fetch_title_media_map
from .rich_text import build_rich_text
from .schemas import (
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


class SeriesDetailSchema(Schema):
    name: str
    slug: str
    description: RichTextSchema = RichTextSchema()
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
        slug=series.slug,
        description=build_rich_text(series, "description", active_claims(series)),
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


@series_router.get("/", response=list[SeriesListItemSchema])
@decorate_view(cache_control(no_cache=True))
def list_series(request: HttpRequest) -> list[SeriesListItemSchema]:
    """Return all series with title count and thumbnail."""
    qs = (
        Series.objects.active()
        .annotate(title_count=Count("titles", filter=active_status_q("titles")))
        .order_by("-title_count", "name")
        .prefetch_related(
            Prefetch(
                "titles__machine_models",
                queryset=MachineModel.objects.active()
                .filter(variant_of__isnull=True)
                .order_by(F("year").asc(nulls_last=True))
                .only("id", "title_id", "extra_data"),
            )
        )
    )
    min_rank = get_minimum_display_rank()
    series_list = list(qs)
    media_by_model = fetch_title_media_map(
        title for s in series_list for title in s.titles.all()
    )
    result: list[SeriesListItemSchema] = []
    for s in series_list:
        thumb = None
        for title in s.titles.all():
            for pm in title.machine_models.all():
                t, _ = extract_image_urls(
                    pm.extra_data or {}, media_by_model.get(pm.pk), min_rank=min_rank
                )
                if t:
                    thumb = t
                    break
            if thumb:
                break
        result.append(
            SeriesListItemSchema(
                name=s.name,
                slug=s.slug,
                description=build_rich_text(s, "description"),
                title_count=cast(HasTitleCount, s).title_count,
                thumbnail_url=thumb,
            )
        )
    return result


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
def patch_series_claims(
    request: HttpRequest, public_id: str, data: ClaimPatchSchema
) -> SeriesDetailSchema:
    """Assert per-field claims from the authenticated user, then re-resolve."""
    check_and_record(request.user, EDIT_RATE_LIMIT_SPEC)

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
