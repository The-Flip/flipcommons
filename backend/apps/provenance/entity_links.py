"""Shared helpers for building entity-link DTOs from content-type refs.

Dereferences ``EntityKey`` content-type pointers into ``EntityLinkSchema``
DTOs (href, name, type label) for the frontend. Used by the user-profile
endpoint and the recent-changes feed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.schemas import EntityLinkSchema
from apps.core.types import EntityKey


def build_entity_href(
    model_class: type[models.Model], entity: models.Model
) -> str | None:
    """Build the frontend URL for a catalog entity from its link_url_pattern."""
    pattern = getattr(model_class, "link_url_pattern", None)
    public_id = getattr(entity, "public_id", None)
    if not isinstance(pattern, str) or not isinstance(public_id, str):
        return None
    return pattern.format(public_id=public_id)


def build_entity_links(
    entity_keys: Sequence[EntityKey],
) -> dict[EntityKey, EntityLinkSchema]:
    """Build entity-link DTOs from a sequence of ``EntityKey`` refs.

    Returns a dict mapping each ``EntityKey`` to its ``EntityLinkSchema``,
    skipping entries whose content type or object cannot be dereferenced.
    """
    # Group by content_type_id, deduplicating object_ids
    by_ct: dict[int, set[int]] = defaultdict(set)
    for key in entity_keys:
        by_ct[key.content_type_id].add(key.object_id)

    links: dict[EntityKey, EntityLinkSchema] = {}
    for ct_id, obj_ids in by_ct.items():
        ct = ContentType.objects.get_for_id(ct_id)
        model_class = ct.model_class()
        if not model_class:
            continue
        entities = model_class._default_manager.in_bulk(list(obj_ids))
        type_label = str(model_class._meta.verbose_name).title()
        for obj_id, entity in entities.items():
            href = build_entity_href(model_class, entity)
            if href is None:
                continue
            name = getattr(entity, "name", None)
            links[EntityKey(ct_id, obj_id)] = EntityLinkSchema(
                href=href,
                name=name if isinstance(name, str) else str(entity),
                type_label=type_label,
            )
    return links
