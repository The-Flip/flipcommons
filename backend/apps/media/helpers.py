"""Helpers for prefetching EntityMedia onto catalog entities and reading it back."""

from __future__ import annotations

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


def primary_media(entity: models.Model) -> list[EntityMedia]:
    """Return primary EntityMedia rows prefetched onto *entity*.

    Raises AssertionError if the queryset wasn't set up with a Prefetch
    using to_attr="primary_media".
    """
    media = getattr(entity, "primary_media", None)
    if media is None:
        raise AssertionError(
            f"{type(entity).__name__} was not loaded with a primary_media prefetch"
        )
    return cast(list[EntityMedia], media)
