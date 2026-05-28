"""Kiosk page API — public, anon-allowed page model for /kiosk display."""

from __future__ import annotations

from django.db.models import Prefetch
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.catalog.api.images import extract_image_urls, fetch_title_media_map
from apps.catalog.api.schemas import EntityRef
from apps.catalog.models import MachineModel
from apps.core.licensing import get_minimum_display_rank
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
    config = get_object_or_404(
        KioskConfig.objects.prefetch_related(
            Prefetch(
                "items__title__machine_models",
                queryset=MachineModel.objects.active()
                .filter(variant_of__isnull=True)
                .select_related("corporate_entity__manufacturer")
                .order_by("year", "name"),
            ),
        ),
        pk=config_id,
    )

    items = list(config.items.select_related("title").order_by("position"))
    titles = [item.title for item in items]
    media_by_model = fetch_title_media_map(titles)
    min_rank = get_minimum_display_rank()

    page_items: list[KioskPageItemSchema] = []
    for item in items:
        title = item.title
        first = next(iter(title.machine_models.all()), None)
        thumbnail_url: str | None = None
        manufacturer: EntityRef | None = None
        year: int | None = None
        if first is not None:
            media = media_by_model.get(first.pk)
            thumbnail_url, _ = extract_image_urls(
                first.extra_data or {}, media, min_rank=min_rank
            )
            year = first.year
            mfr = (
                first.corporate_entity.manufacturer
                if first.corporate_entity and first.corporate_entity.manufacturer
                else None
            )
            if mfr is not None:
                manufacturer = EntityRef(name=mfr.name, public_id=mfr.public_id)
        page_items.append(
            KioskPageItemSchema(
                position=item.position,
                hook=item.hook,
                title=KioskItemTitleSchema(
                    slug=title.slug,
                    name=title.name,
                    thumbnail_url=thumbnail_url,
                    manufacturer=manufacturer,
                    year=year,
                ),
            )
        )

    return KioskPageSchema(
        id=config.pk,
        page_heading=config.page_heading,
        idle_seconds=config.idle_seconds,
        items=page_items,
    )
