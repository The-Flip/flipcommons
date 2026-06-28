"""Helpers for prefetching EntityMedia onto catalog entities and reading it back."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any, cast

from django.db import models
from django.db.models import Prefetch

from .models import EntityMedia


# Slot 2 is Any because prefetch_related has a single _PrefetchedQuerySetT
# TypeVar it must unify across all heterogeneous Prefetch args at the call
# site; any concrete queryset type here breaks that unification. The Any
# is an artifact of django-stubs' API design, not lost information.
def media_prefetch() -> Prefetch[str, Any, str]:
    """Return a Prefetch for ready EntityMedia with assets."""
    return Prefetch(
        "entity_media",
        queryset=EntityMedia.objects.filter(
            asset__status="ready",
        ).select_related("asset", "asset__uploaded_by"),
        to_attr="all_media",
    )


def all_media(entity: models.Model) -> list[EntityMedia]:
    """Return all ready EntityMedia rows prefetched onto *entity*.

    Raises AssertionError if the queryset wasn't set up with
    ``media_prefetch()`` (to_attr="all_media").
    """
    media = getattr(entity, "all_media", None)
    if media is None:
        raise AssertionError(
            f"{type(entity).__name__} was not loaded with media_prefetch()"
        )
    return cast(list[EntityMedia], media)


def displayed_primary_asset_ids(media: Iterable[EntityMedia]) -> set[int]:
    """Return the asset ids that are the *displayed* primary, one per category.

    The stored ``EntityMedia.is_primary`` is the raw claimed value, so a
    category may have zero or several primary-claimed rows.  This selects the
    single displayed primary per category:

    - if any row in a category claims ``is_primary``, the **earliest-uploaded**
      such row wins;
    - otherwise the **earliest-uploaded** row in the category is auto-promoted.

    "Earliest-uploaded" is the lowest ``asset_id`` (monotonic with upload).  It
    is a stable, deterministic key that survives a from-scratch rebuild, unlike
    a materialization timestamp — which collapses when every row is bulk-created
    in one instant.  Rows are grouped by ``category`` (``None`` is its own
    group).
    """
    by_category: dict[str | None, list[EntityMedia]] = defaultdict(list)
    for em in media:
        by_category[em.category].append(em)

    chosen: set[int] = set()
    for rows in by_category.values():
        claimed = [em for em in rows if em.is_primary]
        pool = claimed or rows
        winner = min(pool, key=lambda em: em.asset_id)
        chosen.add(winner.asset_id)
    return chosen


def displayed_primary_media(entity: models.Model) -> list[EntityMedia]:
    """Return the *displayed* primary EntityMedia rows (one per category).

    Reads the full ``all_media`` prefetch and applies
    :func:`displayed_primary_asset_ids`, so it requires the entity to have been
    loaded with ``media_prefetch()``.
    """
    rows = all_media(entity)
    chosen = displayed_primary_asset_ids(rows)
    return [em for em in rows if em.asset_id in chosen]
