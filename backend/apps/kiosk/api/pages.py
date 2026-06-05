"""Kiosk page API — public, anon-allowed page model for /kiosk display."""

from __future__ import annotations

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.catalog.api.images import extract_image_urls, fetch_title_media_map
from apps.core.licensing import get_minimum_display_rank
from apps.kiosk.api._titles import first_model_prefetch, first_model_summary
from apps.kiosk.api.schemas import (
    KioskItemTitleSchema,
    KioskPageItemSchema,
    KioskPageSchema,
)
from apps.kiosk.models import KioskConfig

kiosk_pages_router = Router(tags=["private"])


@kiosk_pages_router.get("{config_id}/", response=KioskPageSchema)
def kiosk_display_page(request: HttpRequest, config_id: int) -> KioskPageSchema:
    """Return the kiosk display page model: config + already-expanded titles."""
    _ = request
    config = get_object_or_404(KioskConfig, pk=config_id)

    items = list(
        config.items.select_related("title")
        .prefetch_related(first_model_prefetch("title__machine_models"))
        .order_by("position")
    )
    titles = [item.title for item in items]
    media_by_model = fetch_title_media_map(titles)
    min_rank = get_minimum_display_rank()

    page_items: list[KioskPageItemSchema] = []
    for item in items:
        title = item.title
        summary = first_model_summary(title)
        thumbnail_url: str | None = None
        if summary.model is not None:
            media = media_by_model.get(summary.model.pk)
            thumbnail_url, _ = extract_image_urls(
                summary.model.extra_data or {}, media, min_rank=min_rank
            )
        page_items.append(
            KioskPageItemSchema(
                position=item.position,
                hook=item.hook,
                title=KioskItemTitleSchema(
                    slug=title.slug,
                    name=title.name,
                    thumbnail_url=thumbnail_url,
                    manufacturer=summary.manufacturer,
                    year=summary.year,
                ),
            )
        )

    return KioskPageSchema(
        id=config.pk,
        page_heading=config.page_heading,
        idle_seconds=config.idle_seconds,
        items=page_items,
    )
