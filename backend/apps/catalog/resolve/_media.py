"""Resolution logic for media_attachment claims → EntityMedia rows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple, cast

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from apps.core.types import ClaimSubjectId, ContentTypeId, EntityKey
from apps.media.models import EntityMedia, MediaAsset, MediaSupportedModel
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Claim

from ..cache import invalidate_response_cache
from ._claim_values import MediaAttachmentClaimValue
from ._engine import Delta, ExtractedMember, MemberMap, RowState, reconcile

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


class CtInfo(NamedTuple):
    """Cached per-content-type metadata used during media resolution."""

    model_class: type | None
    is_media_supported: bool
    categories: list[str]


class MediaPayload(NamedTuple):
    """The materialized attributes of an attachment: its category and primary flag."""

    category: str | None
    is_primary: bool


class MediaProjection:
    """Projection for ``media_attachment`` claims into :class:`EntityMedia` rows.

    Bespoke because the subject is a composite :class:`EntityKey` (media spans
    every media-supported entity type, keyed by content-type + object), and
    category validity is per-entity-type.  Scope (``content_type_id`` /
    ``subject_ids``) is closed over at construction since a composite subject set
    can't be expressed through :func:`reconcile`'s plain ``subjects`` argument;
    the wrapper calls ``reconcile(projection, None)``.

    Claim-local: each winning claim's ``(category, is_primary)`` is materialized
    verbatim — the projection does **not** read sibling attachments.  Selecting a
    single displayed primary per category (and auto-promoting when none is
    claimed) is a read-time concern, see
    :func:`apps.media.helpers.displayed_primary_asset_ids`.
    """

    def __init__(
        self,
        *,
        content_type_id: ContentTypeId | None,
        subject_ids: set[ClaimSubjectId] | None,
    ) -> None:
        self.content_type_id = content_type_id
        self.subject_ids = subject_ids
        self._valid_asset_pks = set(MediaAsset.objects.values_list("pk", flat=True))
        self._ct_cache: dict[int, CtInfo] = {}

    def _ct_info(self, ct_id: int) -> CtInfo:
        if ct_id not in self._ct_cache:
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
            self._ct_cache[ct_id] = CtInfo(model_class, is_supported, categories)
        return self._ct_cache[ct_id]

    def claims(self, subjects: set[EntityKey] | None) -> Iterable[Claim]:
        claims_qs = Claim.objects.filter(field_name="media_attachment")
        if self.content_type_id is not None:
            claims_qs = claims_qs.filter(content_type_id=self.content_type_id)
        if self.subject_ids is not None:
            claims_qs = claims_qs.filter(object_id__in=self.subject_ids)
        return ranked_claims(claims_qs, "content_type_id", "object_id", "claim_key")

    def subject(self, claim: Claim) -> EntityKey:
        return EntityKey(claim.content_type_id, claim.object_id)

    def extract(self, claim: Claim) -> ExtractedMember[int, MediaPayload] | None:
        ct_id = claim.content_type_id
        ct_info = self._ct_info(ct_id)
        if not ct_info.is_media_supported:
            logger.warning(
                "media_attachment claim on non-media-supported entity "
                "(content_type_id=%s, object_id=%s) — skipping",
                ct_id,
                claim.object_id,
            )
            return None

        val = cast(MediaAttachmentClaimValue, claim.value)
        asset_pk = val.get("media_asset")
        if asset_pk not in self._valid_asset_pks:
            logger.warning(
                "Unresolved media_asset pk %r in claim (content_type_id=%s, object_id=%s)",
                asset_pk,
                ct_id,
                claim.object_id,
            )
            return None

        category = val.get("category")
        if category is not None and (
            not ct_info.categories or category not in ct_info.categories
        ):
            logger.warning(
                "Invalid category %r in media_attachment claim "
                "(content_type_id=%s, object_id=%s) — skipping",
                category,
                ct_id,
                claim.object_id,
            )
            return None

        is_primary = bool(val.get("is_primary", False))
        return ExtractedMember(asset_pk, MediaPayload(category, is_primary))

    def read(
        self, subjects: set[EntityKey] | None
    ) -> MemberMap[EntityKey, int, RowState[MediaPayload]]:
        rows_qs = EntityMedia.objects.all()
        if self.content_type_id is not None:
            rows_qs = rows_qs.filter(content_type_id=self.content_type_id)
        if self.subject_ids is not None:
            rows_qs = rows_qs.filter(object_id__in=self.subject_ids)

        existing: MemberMap[EntityKey, int, RowState[MediaPayload]] = {}
        for row in rows_qs.values_list(
            "pk", "content_type_id", "object_id", "asset_id", "category", "is_primary"
        ):
            pk, ct_id, obj_id, asset_id, category, is_primary = row
            existing.setdefault(EntityKey(ct_id, obj_id), {})[asset_id] = RowState(
                pk, MediaPayload(category, is_primary)
            )
        return existing

    def write(self, delta: Delta[EntityKey, int, MediaPayload]) -> None:
        if delta.delete:
            EntityMedia.objects.filter(pk__in=delta.delete).delete()
        if delta.create:
            EntityMedia.objects.bulk_create(
                [
                    EntityMedia(
                        content_type_id=row.subject.content_type_id,
                        object_id=row.subject.object_id,
                        asset_id=row.key,
                        category=row.payload.category,
                        is_primary=row.payload.is_primary,
                    )
                    for row in delta.create
                ],
                batch_size=2000,
            )
        if delta.update:
            fetched = EntityMedia.objects.in_bulk([row.pk for row in delta.update])
            for row in delta.update:
                media_row = fetched[row.pk]
                media_row.category = row.payload.category
                media_row.is_primary = row.payload.is_primary
            EntityMedia.objects.bulk_update(
                list(fetched.values()), ["category", "is_primary"], batch_size=2000
            )


def resolve_media_attachments(
    *,
    content_type_id: ContentTypeId | None = None,
    subject_ids: set[ClaimSubjectId] | None = None,
) -> None:
    """Bulk-resolve ``media_attachment`` claims into :class:`EntityMedia` rows.

    Both parameters are optional.  Passing neither resolves all media across all
    entity types.  Passing both scopes to a single entity.
    """
    projection = MediaProjection(
        content_type_id=content_type_id, subject_ids=subject_ids
    )
    delta = reconcile(projection, None)
    if delta.create or delta.delete or delta.update:
        transaction.on_commit(invalidate_response_cache)
