"""Media upload API endpoint."""

from __future__ import annotations

import logging
import uuid as uuid_lib
from functools import partial
from pathlib import PurePosixPath
from typing import cast

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from ninja import File, Form, Router, Status, UploadedFile
from ninja.errors import HttpError
from ninja.security import django_auth

from apps.accounts.models import User
from apps.catalog.claims import build_media_attachment_claim
from apps.catalog.resolve import resolve_media_attachments
from apps.core.api_helpers import authed_user
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.entity_types import get_linkable_model
from apps.core.schemas import ErrorDetailSchema, ValidationErrorSchema
from apps.media.constants import (
    ALLOWED_IMAGE_EXTENSIONS,
    DISPLAY_MAX_DIMENSION,
    MAX_IMAGE_FILE_SIZE,
    MAX_UPLOADS_PER_HOUR,
    THUMB_MAX_DIMENSION,
)
from apps.media.models import (
    EntityMedia,
    MediaAsset,
    MediaRendition,
    MediaSupportedModel,
)
from apps.media.processing import (
    InvalidImageError,
    check_codec_support,
    generate_rendition,
    process_original,
    validate_image,
)
from apps.media.schemas import (
    AttachmentMetaSchema,
    MediaAssetInputSchema,
    MediaSetCategoryInputSchema,
    RenditionUrlsSchema,
    UploadSchema,
)
from apps.media.storage import (
    build_public_url,
    build_storage_key,
    delete_from_storage,
    upload_to_storage,
)
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim

logger = logging.getLogger(__name__)

media_router = Router(tags=["media", "private"])


def _assert_media_claim(
    entity: MediaSupportedModel,
    *,
    claim_key: str,
    claim_value: object,
    user: User,
) -> Claim:
    """Assert a ``media_attachment`` claim inside a fresh user ChangeSet.

    Every media mutation is one user action, so it gets its own
    ``action=EDIT`` ChangeSet — the single attribution path through
    provenance. Callers must already hold a ``transaction.atomic()`` block so
    the ChangeSet and claim commit together. See docs/plans/auth/Actors.md
    ("Fix Media Claims").
    """
    changeset = ChangeSet.objects.create(user=user, action=ChangeSetAction.EDIT)
    return Claim.objects.assert_claim(
        entity,
        "media_attachment",
        claim_value,
        user=user,
        claim_key=claim_key,
        changeset=changeset,
    )


# Extensions that require optional codecs.
_CODEC_EXTENSIONS: dict[str, str] = {
    ".heic": "heic",
    ".heif": "heif",
    ".avif": "avif",
}


def _delete_media_storage_after_commit(storage_keys: list[str]) -> None:
    """Delete storage files after a successful DB commit."""
    try:
        delete_from_storage(storage_keys)
    except Exception:
        logger.exception("Storage cleanup failed for %d keys", len(storage_keys))


def _check_rate_limit(user_id: int) -> None:
    """Best-effort per-user upload rate limiting via cache.

    Only checks the limit — does not increment. Call _incr_rate_limit()
    after a successful upload so failed attempts don't consume quota.
    """
    key = f"media_upload_count:{user_id}"
    count = cast(int, cache.get_or_set(key, 0, 3600))
    if count >= MAX_UPLOADS_PER_HOUR:
        raise HttpError(429, "Upload limit exceeded. Try again later.")


def _incr_rate_limit(user_id: int) -> None:
    """Increment the upload counter after a successful upload."""
    key = f"media_upload_count:{user_id}"
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, 3600)


def _resolve_entity(
    entity_type: str, public_id: str
) -> tuple[ContentType, MediaSupportedModel]:
    """Resolve ``(entity_type, public_id)`` to ``(ContentType, entity instance)``.

    ``entity_type`` is the canonical hyphenated public identifier declared
    on each :class:`CatalogModel` subclass. Concatenated ContentType
    spellings (``'corporateentity'``) are rejected. ``public_id`` is the
    value of whichever field the model declares as ``public_id_field``
    (defaults to ``slug``).

    Returns (content_type, entity) or raises HttpError.
    """
    try:
        model_class = get_linkable_model(entity_type)
    except ValueError:
        raise HttpError(404, f"Unknown entity_type '{entity_type}'.") from None

    if not issubclass(model_class, MediaSupportedModel):
        raise HttpError(400, f"{entity_type} does not support media attachments.")

    # `_default_manager` rather than `.objects`: `type[<LinkableModel & MediaSupportedModel>]`
    # is an abstract intersection, and `.objects` is attached only to concrete
    # subclasses by Django's metaclass. (Introspection idiom.)
    entity = model_class._default_manager.filter(
        **{model_class.public_id_field: public_id}
    ).first()
    if entity is None:
        raise HttpError(400, f"{entity_type} '{public_id}' not found.")

    ct = ContentType.objects.get_for_model(model_class)
    return ct, entity


@media_router.post(
    "/upload/",
    response={200: UploadSchema, 429: ErrorDetailSchema},
    auth=django_auth,
)
@requires(Activity.MEDIA_EDIT)
def upload_media(
    request: HttpRequest,
    file: File[UploadedFile],
    entity_type: Form[str],
    public_id: Form[str],
    category: Form[str],
) -> UploadSchema:
    """Upload an image and create MediaAsset + MediaRendition rows."""
    user = authed_user(request)
    # --- Rate limit ---
    _check_rate_limit(user.id)

    # --- Validate file extension ---
    original_filename = file.name or "upload"
    ext = PurePosixPath(original_filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HttpError(400, f"File type '{ext}' is not allowed.")

    # --- Codec pre-flight ---
    codec_name = _CODEC_EXTENSIONS.get(ext)
    if codec_name:
        support = check_codec_support()
        if not support.get(codec_name):
            raise HttpError(
                400,
                f"{ext.lstrip('.').upper()} format is not supported on this server.",
            )

    # --- Read and check size ---
    data = file.read()
    if len(data) > MAX_IMAGE_FILE_SIZE:
        size_mb = MAX_IMAGE_FILE_SIZE // (1024 * 1024)
        raise HttpError(400, f"File exceeds maximum size of {size_mb} MB.")

    # --- Resolve entity and validate category ---
    ct, entity = _resolve_entity(entity_type, public_id)
    try:
        # Validate category early (asset_pk=0 is a placeholder — only category
        # validation runs here; the real claim is built after asset creation).
        build_media_attachment_claim(
            entity,
            0,
            category=category,
            is_primary=False,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc

    # --- Validate image ---
    try:
        validate_image(data)
    except InvalidImageError as exc:
        raise HttpError(400, f"Invalid image: {exc}") from exc

    # --- Process ---
    try:
        original = process_original(data)
        thumb = generate_rendition(data, THUMB_MAX_DIMENSION)
        display = generate_rendition(data, DISPLAY_MAX_DIMENSION)
    except InvalidImageError as exc:
        raise HttpError(400, f"Image processing failed: {exc}") from exc

    # --- Build storage keys ---
    asset_uuid = uuid_lib.uuid4()

    key_original = build_storage_key(asset_uuid, "original")
    key_thumb = build_storage_key(asset_uuid, "thumb")
    key_display = build_storage_key(asset_uuid, "display")

    # --- Upload to storage ---
    uploaded_keys: list[str] = []
    try:
        for key, processed in [
            (key_original, original),
            (key_thumb, thumb),
            (key_display, display),
        ]:
            upload_to_storage(key, processed.data, processed.mime_type)
            uploaded_keys.append(key)
    except Exception:
        logger.exception(
            "Storage upload failed, cleaning up %d keys", len(uploaded_keys)
        )
        delete_from_storage(uploaded_keys)
        raise HttpError(500, "Storage upload failed.") from None

    # --- Create DB rows ---
    try:
        with transaction.atomic():
            asset = MediaAsset.objects.create(
                uuid=asset_uuid,
                kind=MediaAsset.Kind.IMAGE,
                status=MediaAsset.Status.READY,
                original_filename=original_filename,
                mime_type=original.mime_type,
                byte_size=len(original.data),
                width=original.width,
                height=original.height,
                uploaded_by=user,
            )

            renditions_data = [
                ("original", original),
                ("thumb", thumb),
                ("display", display),
            ]
            for rtype, processed in renditions_data:
                MediaRendition.objects.create(
                    asset=asset,
                    rendition_type=rtype,
                    mime_type=processed.mime_type,
                    byte_size=len(processed.data),
                    width=processed.width,
                    height=processed.height,
                )

            # Assert media attachment claim and resolve.
            claim_key, claim_value = build_media_attachment_claim(
                entity,
                asset.pk,
                category=category,
                is_primary=False,
            )
            _assert_media_claim(
                entity, claim_key=claim_key, claim_value=claim_value, user=user
            )
            resolve_media_attachments(
                content_type_id=ct.id,
                subject_ids={entity.pk},
            )
    except Exception:
        logger.exception("DB transaction failed, cleaning up storage keys")
        delete_from_storage(uploaded_keys)
        raise HttpError(500, "Failed to save media records.") from None

    _incr_rate_limit(user.id)

    return UploadSchema(
        asset_uuid=str(asset_uuid),
        kind="image",
        status="ready",
        original_filename=original_filename,
        width=original.width,
        height=original.height,
        renditions=RenditionUrlsSchema(
            original=build_public_url(key_original),
            thumb=build_public_url(key_thumb),
            display=build_public_url(key_display),
        ),
        attachment=AttachmentMetaSchema(
            entity_type=entity_type,
            public_id=public_id,
            category=category,
        ),
    )


@media_router.post(
    "/detach/",
    response={204: None, 404: ErrorDetailSchema, 422: ValidationErrorSchema},
    auth=django_auth,
)
@requires(Activity.MEDIA_EDIT)
def detach_media(request: HttpRequest, body: MediaAssetInputSchema) -> Status[None]:
    """Detach a media asset from an entity by asserting an exists=False claim."""
    user = authed_user(request)
    ct, entity = _resolve_entity(body.entity_type, body.public_id)

    try:
        asset = MediaAsset.objects.get(uuid=body.asset_uuid)
    except MediaAsset.DoesNotExist, ValidationError:
        raise HttpError(404, "Media asset not found.") from None

    if not EntityMedia.objects.filter(
        content_type=ct,
        object_id=entity.pk,
        asset=asset,
    ).exists():
        raise HttpError(404, "This asset is not attached to the specified entity.")

    storage_keys = [
        build_storage_key(asset.uuid, rendition_type)
        for rendition_type, _label in MediaRendition.RenditionType.choices
    ]

    with transaction.atomic():
        claim_key, claim_value = build_media_attachment_claim(
            entity,
            asset.pk,
            exists=False,
        )
        _assert_media_claim(
            entity, claim_key=claim_key, claim_value=claim_value, user=user
        )
        resolve_media_attachments(
            content_type_id=ct.id,
            subject_ids={entity.pk},
        )
        asset.delete()
        if storage_keys:
            transaction.on_commit(
                partial(_delete_media_storage_after_commit, storage_keys)
            )

    return Status(204, None)


@media_router.post(
    "/set-primary/",
    response={204: None, 404: ErrorDetailSchema, 422: ValidationErrorSchema},
    auth=django_auth,
)
@requires(Activity.MEDIA_EDIT)
def set_primary(request: HttpRequest, body: MediaAssetInputSchema) -> Status[None]:
    """Set a media asset as primary for its category on an entity."""
    user = authed_user(request)
    ct, entity = _resolve_entity(body.entity_type, body.public_id)

    try:
        asset = MediaAsset.objects.get(uuid=body.asset_uuid)
    except MediaAsset.DoesNotExist, ValidationError:
        raise HttpError(404, "Media asset not found.") from None

    em = EntityMedia.objects.filter(
        content_type=ct,
        object_id=entity.pk,
        asset=asset,
    ).first()
    if em is None:
        raise HttpError(404, "This asset is not attached to the specified entity.")

    with transaction.atomic():
        claim_key, claim_value = build_media_attachment_claim(
            entity,
            asset.pk,
            category=em.category,
            is_primary=True,
        )
        _assert_media_claim(
            entity, claim_key=claim_key, claim_value=claim_value, user=user
        )
        resolve_media_attachments(
            content_type_id=ct.id,
            subject_ids={entity.pk},
        )

    return Status(204, None)


@media_router.post(
    "/set-category/",
    response={
        204: None,
        400: ErrorDetailSchema,
        404: ErrorDetailSchema,
        422: ValidationErrorSchema,
    },
    auth=django_auth,
)
@requires(Activity.MEDIA_EDIT)
def set_category(
    request: HttpRequest, body: MediaSetCategoryInputSchema
) -> Status[None]:
    """Change the category of a media asset already attached to an entity."""
    user = authed_user(request)
    ct, entity = _resolve_entity(body.entity_type, body.public_id)

    try:
        asset = MediaAsset.objects.get(uuid=body.asset_uuid)
    except MediaAsset.DoesNotExist, ValidationError:
        raise HttpError(404, "Media asset not found.") from None

    em = EntityMedia.objects.filter(
        content_type=ct,
        object_id=entity.pk,
        asset=asset,
    ).first()
    if em is None:
        raise HttpError(404, "This asset is not attached to the specified entity.")

    if em.category == body.category:
        return Status(204, None)

    with transaction.atomic():
        try:
            claim_key, claim_value = build_media_attachment_claim(
                entity,
                asset.pk,
                category=body.category,
                is_primary=False,
            )
        except ValueError as exc:
            raise HttpError(400, str(exc)) from exc

        _assert_media_claim(
            entity, claim_key=claim_key, claim_value=claim_value, user=user
        )
        resolve_media_attachments(
            content_type_id=ct.id,
            subject_ids={entity.pk},
        )

    return Status(204, None)


routers = [
    ("/media/", media_router),
]
