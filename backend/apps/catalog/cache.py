"""Server-side response cache for the catalog's few whole-catalog read endpoints.

This is a *response* cache, not a page cache: it stores pre-serialized JSON
(bytes + ETag, indefinite timeout) for a handful of endpoints whose payload is
expensive to build and identical for every visitor in an audience. It exists
only to spare those endpoints a full-catalog rebuild on every request, and is
deliberately small.

What is cached, who reads it, and the cost it avoids:

- Game facet options (``GET /api/pages/games``) — the games listing's filter
  sidebar (manufacturer, theme, feature, player count and the rest). Avoids
  re-aggregating the option lists across the whole catalog.
- Manufacturer facet options (``GET /api/pages/manufacturers``) — the
  /manufacturers filter sidebar.
- Locations tree — the locations-page hierarchy.
- Per-entity-type bulk-export blobs (``GET /api/public/export/<entity>/``) — a flat,
  slug-keyed dump of every active entity of a type, for bulk/external consumers
  (rate-limited, not a per-page UI call). The most expensive payload to rebuild.

What is **not** cached, by design: entity detail pages (a title, model or person
page). They are the hot path and are serialized live on every request, so they
never touch this cache — ``invalidate_response_cache()`` has no bearing on them.

Invalidation is wholesale (every slot, both audiences) and correctness-neutral —
the cache never changes *what* a user sees, only how fast. Three distinct
triggers fire it: ``signals.py`` on any direct catalog model save/delete and on
a ``CONTENT_DISPLAY_POLICY`` change; the per-entity claims resolver via
``transaction.on_commit`` after it writes (``resolve/_dispatch.py``,
``resolve/_media.py``); and the ``ingest_patches`` command, which calls it once
directly at the end of a bulk run (the bulk resolve path deliberately does not
self-invalidate — the command owns the single post-run flush). Wholesale is
intentional: one edit can ripple across entity types (e.g. a Model edit shifts a
Manufacturer's ``model_count``), so per-type scoping would risk stale aggregates.

Cache slots are scoped by content audience (``default`` or ``kiosk``) so that
kiosk requests, which see show-all content, do not share a slot with public
visitors who must not see unlicensed content. The active audience is determined
per request by ``apps.core.licensing.current_audience()``, which the
``KioskDisplayPolicyMiddleware`` sets from the ``mode=kiosk`` cookie.
"""

from __future__ import annotations

import json
from functools import cache as _lru
from hashlib import md5
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from pydantic import TypeAdapter

from apps.core.licensing import current_audience

# Bump when a code change alters a cached payload — its JSON shape *or* the
# values it computes (a fixed aggregate is as stale as a renamed field).
# FileBasedCache writes with
# ``timeout=None`` and can survive a deploy (its dir is not always wiped), while
# ``invalidate_response_cache()`` only runs on data mutation — never on deploy.
# So a shape change without a bump can keep serving old-shaped JSON to the new
# frontend until the next write; versioning the keys orphans the stale entries.
# The version is shared across all bases, so a bump also harmlessly orphans
# unchanged payloads, which rebuild on first read. (Per-bump history: git blame.)
_CACHE_VERSION = "v10"

# No-filter facet option lists for the games listing page (GET /api/pages/games).
# Static between catalog edits, so cached and cleared by invalidate_response_cache().
_GAMES_FACETS_BASE = f"catalog:games:facets:{_CACHE_VERSION}"
# Same, for the /manufacturers page (GET /api/pages/manufacturers).
_MANUFACTURERS_FACETS_BASE = f"catalog:manufacturers:facets:{_CACHE_VERSION}"
_LOCATIONS_TREE_BASE = f"catalog:locations:tree:{_CACHE_VERSION}"
# Per-entity bulk-export blobs (GET /api/public/export/<entity>/). One slot per
# entity_type × audience; cleared wholesale by invalidate_response_cache()
# because a single catalog edit can ripple across entities (e.g. a Model edit
# shifts a Manufacturer's model_count).
_EXPORT_BASE = f"catalog:export:{_CACHE_VERSION}"


@_lru
def export_entity_types() -> tuple[str, ...]:
    """Entity types with a bulk-export endpoint: every linkable ``CatalogModel``,
    sorted. Source of truth for export cache-slot invalidation; ``api.export``
    builds one route per entry. Derived from the model registry (no hand-listing)
    and evaluated lazily because the app registry isn't ready at module import.
    """
    from apps.catalog.models import CatalogModel
    from apps.core.entity_types import all_linkable_models

    return tuple(
        sorted(
            m.entity_type for m in all_linkable_models() if issubclass(m, CatalogModel)
        )
    )


_BASES: tuple[str, ...] = (
    _GAMES_FACETS_BASE,
    _MANUFACTURERS_FACETS_BASE,
    _LOCATIONS_TREE_BASE,
)

_AUDIENCES: tuple[str, ...] = ("default", "kiosk")


def games_facets_key() -> str:
    return f"{_GAMES_FACETS_BASE}:{current_audience()}"


def manufacturers_facets_key() -> str:
    return f"{_MANUFACTURERS_FACETS_BASE}:{current_audience()}"


def locations_tree_key() -> str:
    return f"{_LOCATIONS_TREE_BASE}:{current_audience()}"


def export_key(entity_type: str) -> str:
    return f"{_EXPORT_BASE}:{entity_type}:{current_audience()}"


def get_cached_response(cache_key: str) -> HttpResponse | None:
    """Return a pre-built HttpResponse from cache, or None on miss.

    Cached values are ``(json_bytes, etag)`` tuples written by
    :func:`set_cached_response`.  The ETag is set on the response so
    ``ConditionalGetMiddleware`` can compare it with ``If-None-Match``
    and return 304 without any serialization or hashing.
    """
    cached = cache.get(cache_key)
    if not isinstance(cached, tuple):
        return None
    json_bytes, etag = cached
    response = HttpResponse(json_bytes, content_type="application/json")
    response["ETag"] = etag
    response["Vary"] = "Cookie"
    return response


def set_cached_response(
    cache_key: str,
    adapter: TypeAdapter[Any],
    data: object,
) -> HttpResponse:
    """Serialize *data* to JSON, cache, and return an ``HttpResponse``.

    In ``DEBUG`` mode (dev + CI), *data* is first validated against *adapter*
    so that shape drift fails loudly at the cache boundary. In production the
    validation step is skipped — *data* must already be JSON-serializable
    (plain dicts/lists/scalars). Callers must therefore emit dicts, not
    Pydantic Schema instances, to keep both paths byte-equivalent.
    """
    if settings.DEBUG:
        adapter.validate_python(data)
    json_bytes = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    etag = f'"{md5(json_bytes, usedforsecurity=False).hexdigest()}"'
    cache.set(cache_key, (json_bytes, etag), timeout=None)
    response = HttpResponse(json_bytes, content_type="application/json")
    response["ETag"] = etag
    response["Vary"] = "Cookie"
    return response


def invalidate_response_cache() -> None:
    """Delete all cached catalog endpoint data, across every audience slot."""
    for base in _BASES:
        for audience in _AUDIENCES:
            cache.delete(f"{base}:{audience}")
    # Per-entity export blobs, keyed by the model-derived export entity types.
    for entity_type in export_entity_types():
        for audience in _AUDIENCES:
            cache.delete(f"{_EXPORT_BASE}:{entity_type}:{audience}")
