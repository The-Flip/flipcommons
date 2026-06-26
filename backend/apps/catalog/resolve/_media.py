"""Resolution logic for media_attachment claims → EntityMedia rows."""

from __future__ import annotations

import logging
from typing import NamedTuple, cast

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from apps.core.types import EntityKey
from apps.media.models import EntityMedia, MediaAsset, MediaSupportedModel
from apps.provenance.claim_presence import member_is_present
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim

from ..cache import invalidate_all
from ._claim_values import MediaAttachmentClaimValue
from ._engine import pick_winners

logger = logging.getLogger(__name__)


class CtInfo(NamedTuple):
    """Cached per-content-type metadata used during media resolution."""

    model_class: type | None
    is_media_supported: bool
    categories: list[str]


class MediaRowState(NamedTuple):
    """Existing (or target) EntityMedia row state."""

    row_pk: int
    category: str | None
    is_primary: bool


class DesiredMediaAttachment(NamedTuple):
    """Per-asset desired attachment state within an entity's desired-state map."""

    category: str | None
    is_primary: bool


def resolve_media_attachments(
    *,
    content_type_id: int | None = None,
    subject_ids: set[int] | None = None,
) -> None:
    """Bulk-resolve ``media_attachment`` claims into :class:`EntityMedia` rows.

    Both parameters are optional.  Passing neither resolves all media across
    all entity types.  Passing both scopes to a single entity.

    Claim-local: each winning claim's ``(category, is_primary)`` is materialized
    verbatim — the resolver does **not** read sibling attachments.  Selecting a
    single displayed primary per category (and auto-promoting when none is
    claimed) is a read-time concern, see
    :func:`apps.media.helpers.displayed_primary_asset_ids`.
    """
    # -- Fetch active claims, pick winners ----------------------------------

    claims_qs = Claim.objects.filter(field_name="media_attachment")
    if content_type_id is not None:
        claims_qs = claims_qs.filter(content_type_id=content_type_id)
    if subject_ids is not None:
        claims_qs = claims_qs.filter(object_id__in=subject_ids)
    claims = ranked_claims(claims_qs, "content_type_id", "object_id", "claim_key")

    # Winner per (content_type_id, object_id, claim_key), grouped by entity.
    winners_by_entity = pick_winners(
        claims,
        lambda c: EntityKey(c.content_type_id, c.object_id),
        lambda c: c.claim_key,
    )

    # -- Validate winners & build desired state -----------------------------

    valid_asset_pks = set(MediaAsset.objects.values_list("pk", flat=True))

    _ct_cache: dict[int, CtInfo] = {}

    def _ct_info(ct_id: int) -> CtInfo:
        if ct_id not in _ct_cache:
            ct = ContentType.objects.get_for_id(ct_id)
            model_class = ct.model_class()
            is_supported = model_class is not None and issubclass(
                model_class, MediaSupportedModel
            )
            categories = (
                cast(list[str], getattr(model_class, "MEDIA_CATEGORIES", []))
                if is_supported
                else []
            )
            _ct_cache[ct_id] = CtInfo(model_class, is_supported, categories)
        return _ct_cache[ct_id]

    # Desired: {EntityKey: {asset_pk: DesiredMediaAttachment}}
    desired_by_entity: dict[EntityKey, dict[int, DesiredMediaAttachment]] = {}

    for entity_key, winners in winners_by_entity.items():
        ct_info = _ct_info(entity_key.content_type_id)

        if not ct_info.is_media_supported:
            logger.warning(
                "media_attachment claim on non-media-supported entity "
                "(content_type_id=%s, object_id=%s) — skipping",
                entity_key.content_type_id,
                entity_key.object_id,
            )
            continue

        desired: dict[int, DesiredMediaAttachment] = {}
        for claim in winners.values():
            val = cast(MediaAttachmentClaimValue, claim.value)
            if not member_is_present(claim):
                continue

            asset_pk = val.get("media_asset")
            if asset_pk not in valid_asset_pks:
                logger.warning(
                    "Unresolved media_asset pk %r in claim "
                    "(content_type_id=%s, object_id=%s)",
                    asset_pk,
                    entity_key.content_type_id,
                    entity_key.object_id,
                )
                continue

            category = val.get("category")
            if category is not None and (
                not ct_info.categories or category not in ct_info.categories
            ):
                logger.warning(
                    "Invalid category %r in media_attachment claim "
                    "(content_type_id=%s, object_id=%s) — skipping",
                    category,
                    entity_key.content_type_id,
                    entity_key.object_id,
                )
                continue

            is_primary = bool(val.get("is_primary", False))
            desired[asset_pk] = DesiredMediaAttachment(category, is_primary)

        desired_by_entity[entity_key] = desired

    # -- Fetch existing EntityMedia rows ------------------------------------

    existing_qs = EntityMedia.objects.all()
    if content_type_id is not None:
        existing_qs = existing_qs.filter(content_type_id=content_type_id)
    if subject_ids is not None:
        existing_qs = existing_qs.filter(object_id__in=subject_ids)

    existing_by_entity: dict[EntityKey, dict[int, MediaRowState]] = {}
    for row in existing_qs.values_list(
        "pk", "content_type_id", "object_id", "asset_id", "category", "is_primary"
    ):
        pk, ct_id, obj_id, asset_id, category, is_primary = row
        existing_by_entity.setdefault(EntityKey(ct_id, obj_id), {})[asset_id] = (
            MediaRowState(pk, category, is_primary)
        )

    # -- Three-way diff -----------------------------------------------------

    to_create: list[EntityMedia] = []
    to_delete_pks: list[int] = []
    to_update: list[MediaRowState] = []

    all_entity_keys = set(desired_by_entity) | set(existing_by_entity)

    for entity_key in all_entity_keys:
        desired = desired_by_entity.get(entity_key, {})
        existing = existing_by_entity.get(entity_key, {})

        for asset_pk, d in desired.items():
            if asset_pk not in existing:
                to_create.append(
                    EntityMedia(
                        content_type_id=entity_key.content_type_id,
                        object_id=entity_key.object_id,
                        asset_id=asset_pk,
                        category=d.category,
                        is_primary=d.is_primary,
                    )
                )
            else:
                existing_row = existing[asset_pk]
                if (
                    existing_row.category != d.category
                    or existing_row.is_primary != d.is_primary
                ):
                    to_update.append(
                        MediaRowState(existing_row.row_pk, d.category, d.is_primary)
                    )

        for asset_pk, existing_row in existing.items():
            if asset_pk not in desired:
                to_delete_pks.append(existing_row.row_pk)

    # -- Apply --------------------------------------------------------------

    if to_delete_pks:
        EntityMedia.objects.filter(pk__in=to_delete_pks).delete()
    if to_create:
        EntityMedia.objects.bulk_create(to_create, batch_size=2000)
    if to_update:
        rows = EntityMedia.objects.in_bulk([update.row_pk for update in to_update])
        for update in to_update:
            media_row = rows[update.row_pk]
            media_row.category = update.category
            media_row.is_primary = update.is_primary
        EntityMedia.objects.bulk_update(
            list(rows.values()), ["category", "is_primary"], batch_size=2000
        )

    if to_delete_pks or to_create or to_update:
        transaction.on_commit(invalidate_all)
