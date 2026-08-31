"""Server-side response cache for endpoints whose payload is expensive to
build and identical for every caller in an audience.

Stores ``(json_bytes, etag)`` — pre-serialized bytes, not a live object graph.
A hit therefore costs one cache read: no unpickling a materialized payload and
no re-encoding it to the same bytes. The ETag rides along so
``ConditionalGetMiddleware`` can answer ``If-None-Match`` without rehashing the
body, and so a hit never re-hashes it either.

Key naming, TTL and invalidation belong to the caller:

- ``apps.catalog.cache`` — audience-scoped keys, no TTL, explicit invalidation
  on catalog writes.
- ``apps.core.api.sitemap`` — one key, a TTL, no invalidation.

``json.dumps`` is the only encoder, so payloads must be plain JSON-serializable
data (dicts, lists, scalars). A value it can't encode raises rather than
serializing by some other route — which is what keeps the cached bytes and the
freshly-built response byte-identical.
"""

from __future__ import annotations

import json
from hashlib import md5
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from pydantic import TypeAdapter


def get_cached_response(
    cache_key: str, *, vary: str | None = None
) -> HttpResponse | None:
    """Return a pre-built ``HttpResponse`` from cache, or ``None`` on miss.

    Cached values are ``(json_bytes, etag)`` tuples written by
    :func:`set_cached_response`.
    """
    cached = cache.get(cache_key)
    if not isinstance(cached, tuple):
        return None
    json_bytes, etag = cached
    return _json_response(json_bytes, etag, vary)


def set_cached_response(
    cache_key: str,
    adapter: TypeAdapter[Any],
    data: object,
    *,
    timeout: int | None,
    vary: str | None = None,
) -> HttpResponse:
    """Serialize *data* to JSON, cache it under *cache_key*, and return an ``HttpResponse``.

    *timeout* is the TTL in seconds, or ``None`` to store indefinitely — in
    which case the caller owns eviction.

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
    cache.set(cache_key, (json_bytes, etag), timeout=timeout)
    return _json_response(json_bytes, etag, vary)


def _json_response(json_bytes: bytes, etag: str, vary: str | None) -> HttpResponse:
    response = HttpResponse(json_bytes, content_type="application/json")
    response["ETag"] = etag
    if vary is not None:
        response["Vary"] = vary
    return response
