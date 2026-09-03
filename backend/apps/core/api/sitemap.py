"""``GET /api/sitemap/`` — derives feeds from every ``SitemappedModel``.

A single endpoint returns every feed in one shot, cached as pre-serialized
bytes in the shared Django cache. The SvelteKit ``/sitemap[[page]].xml`` server
route is the only public caller and arrives from the Node container's
single IP, so an IP-keyed rate limiter would just 429 the entire sitemap
render on post-deploy cache-miss bursts. The cache collapses the cost
ceiling to one materialization for the cache TTL across all Gunicorn
workers, which is the workload we actually care about bounding.
"""

from __future__ import annotations

from datetime import datetime

from django.http import HttpRequest, HttpResponse
from ninja import Router
from pydantic import TypeAdapter

from apps.core.api.sitemap_schemas import (
    SitemapEntryDict,
    SitemapFeedDict,
    SitemapPayloadDict,
    SitemapResponseSchema,
)
from apps.core.response_cache import get_cached_response, set_cached_response
from apps.core.sitemap import all_sitemap_feeds

sitemap_router = Router()

SITEMAP_CACHE_KEY = "core:sitemap:feeds"
SITEMAP_CACHE_TTL = 3600  # seconds

_PAYLOAD_ADAPTER: TypeAdapter[SitemapResponseSchema] = TypeAdapter(
    SitemapResponseSchema
)


def _lastmod(value: datetime) -> str:
    """Format a ``lastmod`` exactly as ``DjangoJSONEncoder`` would.

    The payload carries one datetime per entry — tens of thousands of them —
    and leaving them for the JSON encoder's ``default`` hook would re-format
    every one on every request. Formatting here moves that cost onto the
    once-per-TTL miss instead. The parity test in
    ``apps/core/tests/test_sitemap_api.py`` pins the two formats together.
    """
    text = value.isoformat()
    if value.microsecond:
        # Microseconds down to milliseconds: drop the trailing three digits.
        text = text[:23] + text[26:]
    if text.endswith("+00:00"):
        text = f"{text[:-6]}Z"
    return text


def _build_payload() -> SitemapPayloadDict:
    """Every ``SitemappedModel`` feed as plain JSON-ready data.

    Dicts rather than ``SitemapResponseSchema`` instances: the response cache
    encodes with ``json.dumps``, which cannot serialize a Schema.
    """
    return SitemapPayloadDict(
        feeds=[
            SitemapFeedDict(
                kind=feed.kind,
                entries=[
                    SitemapEntryDict(slug=entry.slug, lastmod=_lastmod(entry.lastmod))
                    for entry in feed.entries
                ],
                max_lastmod=_lastmod(feed.max_lastmod) if feed.max_lastmod else None,
            )
            for feed in all_sitemap_feeds()
        ]
    )


@sitemap_router.get("", response=SitemapResponseSchema)
def get_sitemap(request: HttpRequest) -> HttpResponse:
    """Return every ``SitemappedModel`` feed in a single payload.

    Cached process-wide for ``SITEMAP_CACHE_TTL`` seconds, so a hit is one
    cache read rather than a rebuild or a re-encode. ``Cache-Control`` asks
    downstream callers (the SvelteKit endpoint, crawlers if exposed directly)
    to cache for the same window.

    ``response=`` still declares the schema so OpenAPI and the frontend
    codegen see it; Ninja passes an ``HttpResponse`` through untouched.
    """
    response = get_cached_response(SITEMAP_CACHE_KEY)
    if response is None:
        response = set_cached_response(
            SITEMAP_CACHE_KEY,
            _PAYLOAD_ADAPTER,
            _build_payload(),
            timeout=SITEMAP_CACHE_TTL,
        )
    response["Cache-Control"] = f"public, max-age={SITEMAP_CACHE_TTL}"
    return response
