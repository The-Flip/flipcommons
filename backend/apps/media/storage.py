"""Storage key generation and helpers for the media app.

Storage keys are derived at runtime from asset UUID + rendition type.
Nothing about storage paths is stored in the database.
"""

from __future__ import annotations

import logging
from typing import NamedTuple
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage, default_storage

from apps.media.constants import STORAGE_PREFIX
from apps.media.models import MediaRendition

logger = logging.getLogger(__name__)

_VALID_RENDITION_TYPES = {v.value for v in MediaRendition.RenditionType}


def build_storage_key(asset_uuid: UUID, rendition_type: str) -> str:
    """Derive the storage key for a rendition.

    Keys are deterministic from asset UUID + rendition type alone.
    Content-Type is stored as object metadata by the storage backend,
    not encoded in the key.
    """
    if rendition_type not in _VALID_RENDITION_TYPES:
        msg = f"Invalid rendition_type: {rendition_type!r}"
        raise ValueError(msg)

    return f"{STORAGE_PREFIX}/{asset_uuid}/{rendition_type}"


def build_public_url(storage_key: str) -> str:
    """Build a public URL for a storage key."""
    base = settings.MEDIA_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/{storage_key}"


def get_media_storage() -> Storage:
    """Return the configured default storage backend."""
    return default_storage


class _TypedContentFile(ContentFile[bytes]):
    """ContentFile that advertises a content_type attribute.

    django-storages' S3Boto3Storage forwards ``file.content_type`` to S3
    as the object's Content-Type when the attribute is present. Declaring
    it on a subclass lets us set it without a cast.
    """

    content_type: str


def upload_to_storage(storage_key: str, data: bytes, content_type: str) -> None:
    """Write bytes to storage at the given key.

    Verifies the storage backend used the exact key we requested.
    S3Boto3Storage can silently rename keys when ``file_overwrite=False``
    (its default) and a collision occurs.  With UUID-based keys this is
    near-impossible, but we check anyway to prevent silent mismatches
    between the DB and storage.
    """
    storage = get_media_storage()
    file = _TypedContentFile(data, name=storage_key)
    file.content_type = content_type
    actual_key = storage.save(storage_key, file)
    if actual_key != storage_key:
        storage.delete(actual_key)
        msg = f"Storage key mismatch: expected {storage_key}, got {actual_key}"
        raise RuntimeError(msg)


class MagicSignature(NamedTuple):
    signature: bytes
    offset: int
    mime_type: str


_MAGIC_SIGNATURES: list[MagicSignature] = [
    MagicSignature(b"\xff\xd8\xff", 0, "image/jpeg"),
    MagicSignature(b"\x89PNG", 0, "image/png"),
    MagicSignature(b"WEBP", 8, "image/webp"),  # RIFF....WEBP
    MagicSignature(b"ftypavif", 4, "image/avif"),  # ISOBMFF ftyp box
]


def sniff_image_content_type(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes.

    Returns None if no known signature matches.  Used by the dev-only
    media serving view where extensionless storage keys prevent
    Django's default Content-Type guessing.
    """
    for sig in _MAGIC_SIGNATURES:
        if data[sig.offset : sig.offset + len(sig.signature)] == sig.signature:
            return sig.mime_type
    return None


def delete_from_storage(storage_keys: list[str]) -> list[str]:
    """Best-effort deletion of storage objects; returns the keys still in storage."""
    storage = get_media_storage()
    leaked: list[str] = []
    for key in storage_keys:
        try:
            storage.delete(key)
        except Exception:
            logger.warning("Failed to delete storage key %s", key, exc_info=True)
            leaked.append(key)
    return leaked
