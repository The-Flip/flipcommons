"""Cache keys and invalidation helpers for the catalog app.

Cache slots are scoped by content audience (``default`` or ``kiosk``) so that
kiosk requests, which see show-all content, do not share a slot with
public visitors who must not see unlicensed content. The active audience
is determined per request by ``apps.core.licensing.current_audience()``,
which the ``KioskDisplayPolicyMiddleware`` sets from the ``mode=kiosk``
cookie.
"""

from __future__ import annotations

import json
from hashlib import md5
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from pydantic import TypeAdapter

from apps.core.licensing import current_audience

# Bump when a cached /all/ payload's JSON shape changes. FileBasedCache writes
# with ``timeout=None`` and can survive a deploy (its dir is not always wiped),
# while ``invalidate_all()`` only runs on data mutation — never on deploy. So a
# shape change without a version bump can keep serving old-shaped JSON to the
# new frontend until the next write. Versioning the keys orphans the stale
# entries instead. (The unversioned keys were the implicit "v1"; v2 = the
# public_id reference-body migration that reshaped titles/manufacturers refs.)
_CACHE_VERSION = "v2"

_MODELS_ALL_BASE = f"catalog:models:all:{_CACHE_VERSION}"
_MANUFACTURERS_ALL_BASE = f"catalog:manufacturers:all:{_CACHE_VERSION}"
_PEOPLE_ALL_BASE = f"catalog:people:all:{_CACHE_VERSION}"
_TITLES_ALL_BASE = f"catalog:titles:all:{_CACHE_VERSION}"
_LOCATIONS_TREE_BASE = f"catalog:locations:tree:{_CACHE_VERSION}"

_BASES: tuple[str, ...] = (
    _MODELS_ALL_BASE,
    _MANUFACTURERS_ALL_BASE,
    _PEOPLE_ALL_BASE,
    _TITLES_ALL_BASE,
    _LOCATIONS_TREE_BASE,
)

_AUDIENCES: tuple[str, ...] = ("default", "kiosk")


def models_all_key() -> str:
    return f"{_MODELS_ALL_BASE}:{current_audience()}"


def manufacturers_all_key() -> str:
    return f"{_MANUFACTURERS_ALL_BASE}:{current_audience()}"


def people_all_key() -> str:
    return f"{_PEOPLE_ALL_BASE}:{current_audience()}"


def titles_all_key() -> str:
    return f"{_TITLES_ALL_BASE}:{current_audience()}"


def locations_tree_key() -> str:
    return f"{_LOCATIONS_TREE_BASE}:{current_audience()}"


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


def invalidate_all() -> None:
    """Delete all cached /all/ endpoint data, across every audience slot."""
    for base in _BASES:
        for audience in _AUDIENCES:
            cache.delete(f"{base}:{audience}")
