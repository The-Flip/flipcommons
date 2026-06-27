"""Signal handlers to invalidate cached catalog endpoint data on model changes."""

from __future__ import annotations

from typing import Any

from constance.signals import config_updated
from django.db import models
from django.db.models.signals import post_delete, post_save

from .cache import invalidate_response_cache


def _invalidate_cache(
    sender: type[models.Model],
    **kwargs: Any,  # noqa: ANN401 - Django signal kwargs are framework-owned
) -> None:
    invalidate_response_cache()


# Constance's config_updated signal passes arbitrary value types (whatever the
# changed setting holds — str, int, bool, etc.) and reserves the right to add
# keyword arguments, so this is a framework-owned callback surface.
def _invalidate_cache_on_policy_change(
    sender: Any,  # noqa: ANN401 — constance signal sender
    key: str,
    old_value: Any,  # noqa: ANN401 — constance setting value, arbitrary type
    new_value: Any,  # noqa: ANN401 — constance setting value, arbitrary type
    **kwargs: Any,  # noqa: ANN401 — Django signal framework passthrough
) -> None:
    if key == "CONTENT_DISPLAY_POLICY":
        invalidate_response_cache()


def _cache_invalidating_models() -> list[type[models.Model]]:
    """Derive the set of models whose saves/deletes should bust the catalog cache.

    Walks the catalog app registry for concrete ``CatalogModel`` subclasses,
    then appends the two through-rows (``CorporateEntityLocation``, ``Credit``)
    that surface in cached facet payloads but aren't top-level entities.
    """
    from ._walks import catalog_models
    from .models import CorporateEntityLocation, Credit

    derived = catalog_models()
    extras: list[type[models.Model]] = [CorporateEntityLocation, Credit]
    # Not covered here: MachineModel* through-rows (MachineModelTheme, etc.)
    # and AliasModel subclasses. Those are written by the claims resolver,
    # which calls invalidate_response_cache() directly via transaction.on_commit (see
    # resolve/_dispatch.py). EntityMedia is also written via the resolver
    # (resolve/_media.py uses bulk_create, which doesn't fire post_save), and
    # busts the cache the same way. Direct edits outside the claims pipeline
    # would bypass this signal, but that's a policy violation, not a missed
    # path.
    return [*derived, *extras]


def connect() -> None:
    """Connect cache-invalidation signals. Called from AppConfig.ready()."""
    for model in _cache_invalidating_models():
        uid = f"invalidate_cache_{model.__name__}"
        post_save.connect(_invalidate_cache, sender=model, dispatch_uid=f"{uid}_save")
        post_delete.connect(
            _invalidate_cache, sender=model, dispatch_uid=f"{uid}_delete"
        )
    config_updated.connect(
        _invalidate_cache_on_policy_change,
        dispatch_uid="invalidate_cache_on_content_display_policy",
    )
