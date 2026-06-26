"""Image and uploaded-media helpers for catalog API endpoints."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from django.contrib.contenttypes.models import ContentType

from apps.core.licensing import (
    UNKNOWN_LICENSE_RANK,
    get_minimum_display_rank,
)
from apps.core.types import JsonData
from apps.media.helpers import displayed_primary_asset_ids
from apps.media.models import EntityMedia
from apps.media.storage import build_public_url, build_storage_key
from apps.provenance.schemas import AttributionSchema

from ..models import CorporateEntity, MachineModel, Title

__all__ = [
    "extract_image_attribution",
    "extract_image_urls",
    "fetch_model_media_map",
    "fetch_title_media_map",
    "first_thumbnail",
]


def fetch_model_media_map(
    model_ids: Iterable[int],
) -> dict[int, list[EntityMedia]]:
    """Return ``{model_id: [displayed-primary EntityMedia rows]}`` for the
    given MachineModel ids.

    ``is_primary`` stores the raw claimed value, so the displayed primary is a
    read-time selection: this loads all ``asset__status="ready"`` rows per model
    (one indexed query joined to ``MediaAsset``) and applies
    :func:`displayed_primary_asset_ids` per model — the shape
    ``extract_image_urls`` expects via its ``primary_media`` parameter.
    """
    ids = list(model_ids)
    if not ids:
        return {}
    ct = ContentType.objects.get_for_model(MachineModel)
    all_rows: dict[int, list[EntityMedia]] = defaultdict(list)
    for em in (
        EntityMedia.objects.filter(
            content_type=ct,
            object_id__in=ids,
            asset__status="ready",
        )
        .select_related("asset")
        .order_by("created_at")
    ):
        all_rows[em.object_id].append(em)
    grouped: dict[int, list[EntityMedia]] = {}
    for model_id, rows in all_rows.items():
        chosen = displayed_primary_asset_ids(rows)
        grouped[model_id] = [em for em in rows if em.asset_id in chosen]
    return grouped


def fetch_title_media_map(
    titles: Iterable[Title],
) -> dict[int, list[EntityMedia]]:
    """Build the model media map for every MachineModel under *titles*.

    Requires ``machine_models`` to be prefetched on each title — otherwise
    walking ``title.machine_models.all()`` triggers one query per title.
    """
    return fetch_model_media_map(pm.pk for t in titles for pm in t.machine_models.all())


def _uploaded_image_urls(
    primary_media: Sequence[EntityMedia] | None,
) -> tuple[str | None, str | None]:
    """Return (thumbnail_url, hero_image_url) from prefetched EntityMedia.

    Prefers ``backglass`` category, then falls back to any primary.
    Returns ``(None, None)`` when no uploaded media is available.
    """
    if not primary_media:
        return None, None

    # Prefer backglass, fall back to first available primary.
    chosen = None
    for em in primary_media:
        if em.category == "backglass":
            chosen = em
            break
    if chosen is None:
        chosen = primary_media[0]

    asset_uuid = chosen.asset.uuid
    thumb = build_public_url(build_storage_key(asset_uuid, "thumb"))
    hero = build_public_url(build_storage_key(asset_uuid, "display"))
    return thumb, hero


def extract_image_urls(
    extra_data: JsonData,
    primary_media: Sequence[EntityMedia] | None,
    *,
    min_rank: int | None = None,
) -> tuple[str | None, str | None]:
    """Return (thumbnail_url, hero_image_url).

    When *primary_media* (prefetched ``EntityMedia`` rows) contains uploaded
    images, those are used unconditionally (no license gating — this project owns
    them).  Otherwise falls back to third-party images in *extra_data*,
    respecting the global Constance display threshold.

    *primary_media* is required-positional: callers must pass either a list of
    rows or ``None`` to opt out.  This forces every site to make the
    media-vs-extra_data choice deliberately rather than silently defaulting to
    extra_data only.

    Pass *min_rank* to avoid repeated Constance DB lookups in tight loops.
    """
    # Uploaded media always wins — no license gating.
    thumb, hero = _uploaded_image_urls(primary_media)
    if thumb or hero:
        return thumb, hero

    if min_rank is None:
        min_rank = get_minimum_display_rank()

    def _rank_ok(key: str) -> bool:
        rank = extra_data.get(f"{key}.__permissiveness_rank")
        effective = rank if isinstance(rank, int) else UNKNOWN_LICENSE_RANK
        return effective >= min_rank

    def _abs(url: str | None) -> str | None:
        """Return *url* only if it's an absolute HTTP(S) URL, else None."""
        if url and (url.startswith("http://") or url.startswith("https://")):
            return url
        return None

    # Try OPDB structured images first (have size variants).
    images = extra_data.get("opdb.images")
    if images and isinstance(images, list) and _rank_ok("opdb.images"):
        img = None
        for candidate in images:
            if isinstance(candidate, dict) and candidate.get("primary"):
                img = candidate
                break
        if img is None:
            img = images[0] if images else None
        if isinstance(img, dict):
            urls = img.get("urls") or {}
            thumbnail = _abs(urls.get("medium") or urls.get("small"))
            hero = _abs(urls.get("large") or urls.get("medium"))
            if thumbnail or hero:
                return thumbnail, hero

    # Fall back to flat URL list (IPDB-sourced or scraped).
    for key in ("ipdb.image_urls", "image_urls"):
        image_urls = extra_data.get(key)
        if image_urls and isinstance(image_urls, list) and _rank_ok(key):
            first = image_urls[0]
            if isinstance(first, str) and _abs(first):
                return first, first

    return None, None


def extract_image_attribution(
    extra_data: JsonData,
    primary_media: Sequence[EntityMedia] | None,
    *,
    min_rank: int | None = None,
) -> AttributionSchema | None:
    """Return AttributionSchema for the displayed image, or None.

    When uploaded media is being used (determined by *primary_media*), returns
    ``None`` — no third-party license to cite.  Otherwise checks each external
    image source in priority order and returns info for the first source that
    passes the display threshold.

    Pass *min_rank* to avoid repeated Constance DB lookups in tight loops
    (mirrors :func:`extract_image_urls`).
    """
    # Uploaded media has no third-party attribution.
    if primary_media:
        return None

    if min_rank is None:
        min_rank = get_minimum_display_rank()

    for key in ("opdb.images", "ipdb.image_urls", "image_urls"):
        data = extra_data.get(key)
        if not data:
            continue
        rank_raw = extra_data.get(f"{key}.__permissiveness_rank")
        rank = rank_raw if isinstance(rank_raw, int) else None
        effective = rank if rank is not None else UNKNOWN_LICENSE_RANK
        if effective >= min_rank:
            license_slug_raw = extra_data.get(f"{key}.__license_slug")
            license_slug = (
                license_slug_raw if isinstance(license_slug_raw, str) else None
            )
            return AttributionSchema(
                license_slug=license_slug,
            )

    return None


def first_thumbnail(
    entities_with_models: Iterable[CorporateEntity], *, min_rank: int
) -> str | None:
    """Return the first non-None thumbnail URL from nested entity→model prefetches.

    Note: this currently checks only ``extra_data`` — uploaded media on these
    nested models is not considered.  Acceptable today (the locations endpoint
    is the only caller and uploads aren't expected on entity→models there);
    revisit when locations cards need uploaded backglass support.
    """
    for entity in entities_with_models:
        for model in entity.models.all():
            if model.extra_data:
                thumb, _ = extract_image_urls(model.extra_data, None, min_rank=min_rank)
                if thumb:
                    return thumb
    return None
