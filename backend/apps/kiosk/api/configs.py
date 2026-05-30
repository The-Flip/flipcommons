"""Kiosk resource API — CRUD over KioskConfig.

Plain Django models, no claims plumbing: kiosk configs are operational
settings, not user-inputted catalog fields.

All endpoints gate on ``Activity.KIOSK_EDIT``; the policy in
``apps/kiosk/authz.py`` owns the superuser predicate.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status
from ninja.security import django_auth

from apps.catalog.api.schemas import EntityRef
from apps.catalog.models import Title
from apps.core.api_helpers import authed_user
from apps.core.authz.markers import requires
from apps.core.authz.schemas import PolicyDeniedSchema
from apps.core.authz.types import Activity
from apps.core.schemas import ErrorDetailSchema
from apps.kiosk.api.schemas import (
    KioskConfigDetailSchema,
    KioskConfigItemDetailSchema,
    KioskConfigListItemSchema,
    KioskConfigPatchSchema,
)
from apps.kiosk.models import IDLE_SECONDS_MIN, KioskConfig, KioskConfigItem

kiosk_configs_router = Router(tags=["kiosk", "private"])


# ── Helpers ──────────────────────────────────────────────────────────


def _serialize_item(item: KioskConfigItem) -> KioskConfigItemDetailSchema:
    return KioskConfigItemDetailSchema(
        id=item.pk,
        position=item.position,
        hook=item.hook,
        title=EntityRef(name=item.title.name, public_id=item.title.public_id),
    )


def _serialize_detail(config: KioskConfig) -> KioskConfigDetailSchema:
    items = list(config.items.select_related("title"))
    return KioskConfigDetailSchema(
        id=config.pk,
        page_heading=config.page_heading,
        idle_seconds=config.idle_seconds,
        items=[_serialize_item(item) for item in items],
    )


# ── Endpoints ────────────────────────────────────────────────────────


@kiosk_configs_router.get(
    "configs/",
    auth=django_auth,
    response=list[KioskConfigListItemSchema],
)
@requires(Activity.KIOSK_EDIT)
def list_configs(request: HttpRequest) -> list[KioskConfigListItemSchema]:
    configs = KioskConfig.objects.annotate(item_count=Count("items"))
    return [
        KioskConfigListItemSchema(
            id=c.pk,
            page_heading=c.page_heading,
            idle_seconds=c.idle_seconds,
            item_count=c.item_count,
        )
        for c in configs
    ]


@kiosk_configs_router.post(
    "configs/",
    auth=django_auth,
    response={
        201: KioskConfigDetailSchema,
        403: PolicyDeniedSchema | ErrorDetailSchema,
    },
)
@requires(Activity.KIOSK_EDIT)
def create_config(request: HttpRequest) -> Status[KioskConfigDetailSchema]:
    """Create an empty kiosk.

    Audit fields come from ``request.user`` — we don't accept them in the
    payload. Operators identify kiosks by their integer primary key, so no
    label is required at creation time.
    """
    user = authed_user(request)
    config = KioskConfig.objects.create(created_by=user, updated_by=user)
    return Status(201, _serialize_detail(config))


@kiosk_configs_router.get(
    "configs/{config_id}/",
    auth=django_auth,
    response=KioskConfigDetailSchema,
)
@requires(Activity.KIOSK_EDIT)
def get_config(request: HttpRequest, config_id: int) -> KioskConfigDetailSchema:
    config = get_object_or_404(KioskConfig, pk=config_id)
    return _serialize_detail(config)


@kiosk_configs_router.patch(
    "configs/{config_id}/",
    auth=django_auth,
    response={
        200: KioskConfigDetailSchema,
        404: ErrorDetailSchema,
        422: ErrorDetailSchema,
    },
)
@requires(Activity.KIOSK_EDIT)
def update_config(
    request: HttpRequest, config_id: int, data: KioskConfigPatchSchema
) -> KioskConfigDetailSchema:
    """Update scalars and/or fully replace items in one transaction."""
    user = authed_user(request)
    config = get_object_or_404(KioskConfig, pk=config_id)

    # Validate idle_seconds at the boundary so users get a friendly message
    # instead of the raw "CHECK constraint failed: ..." IntegrityError.
    if data.idle_seconds is not None and data.idle_seconds < IDLE_SECONDS_MIN:
        raise HttpError(422, "Idle timeout must be at least 1 second.")

    with transaction.atomic():
        scalar_changed = False
        if data.page_heading is not None and data.page_heading != config.page_heading:
            config.page_heading = data.page_heading
            scalar_changed = True
        if data.idle_seconds is not None and data.idle_seconds != config.idle_seconds:
            config.idle_seconds = data.idle_seconds
            scalar_changed = True
        config.updated_by = user
        if scalar_changed:
            # Boundary validation above covers the only declared CheckConstraint
            # (idle_seconds >= 1). Any IntegrityError reaching this save is an
            # unanticipated bug — let it 500 so we hear about it, rather than
            # leaking the raw constraint message to the client.
            config.save()
        else:
            # Always bump audit fields + updated_at, even on items-only edits.
            config.save(update_fields=["updated_by", "updated_at"])

        if data.items is not None:
            # Full replacement avoids the (config, position) UniqueConstraint
            # footgun on naive in-place updates. List is small (10–30 items).
            slugs = [item.title_slug for item in data.items]
            titles_by_slug = {t.slug: t for t in Title.objects.filter(slug__in=slugs)}
            missing = [s for s in slugs if s not in titles_by_slug]
            if missing:
                raise HttpError(422, f"Unknown title slugs: {missing}")

            config.items.all().delete()
            KioskConfigItem.objects.bulk_create(
                [
                    KioskConfigItem(
                        config=config,
                        title=titles_by_slug[item.title_slug],
                        hook=item.hook,
                        position=item.position,
                    )
                    for item in data.items
                ]
            )

    config.refresh_from_db()
    return _serialize_detail(config)


@kiosk_configs_router.delete(
    "configs/{config_id}/",
    auth=django_auth,
    response={204: None, 404: ErrorDetailSchema},
)
@requires(Activity.KIOSK_EDIT)
def delete_config(request: HttpRequest, config_id: int) -> Status[None]:
    config = get_object_or_404(KioskConfig, pk=config_id)
    config.delete()
    return Status(204, None)
