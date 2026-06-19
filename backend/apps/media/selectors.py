"""Selectors that project EntityMedia rows into API wire schemas.

Sits a tier above ``storage``/``schemas`` because it composes both into the
uploaded-media response shape — unlike ``helpers``, which reads prefetched
rows off entities without touching either.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import EntityMedia
from .schemas import MediaRenditionsSchema, UploadedMediaSchema
from .storage import build_public_url, build_storage_key


def serialize_uploaded_media(
    all_media: Iterable[EntityMedia],
) -> list[UploadedMediaSchema]:
    """Serialize EntityMedia rows into the uploaded_media response list."""
    return [
        UploadedMediaSchema(
            asset_uuid=str(em.asset.uuid),
            category=em.category,
            is_primary=em.is_primary,
            uploaded_by_username=(
                em.asset.uploaded_by.username if em.asset.uploaded_by else None
            ),
            renditions=MediaRenditionsSchema(
                thumb=build_public_url(build_storage_key(em.asset.uuid, "thumb")),
                display=build_public_url(build_storage_key(em.asset.uuid, "display")),
            ),
        )
        for em in all_media
    ]
