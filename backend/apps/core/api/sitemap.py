"""``GET /api/sitemap/`` — derives feeds from every ``SitemappedModel``.

A single endpoint returns every feed in one shot, cached in the shared
Django cache. The SvelteKit ``/sitemap[[page]].xml`` server
route is the only public caller and arrives from the Node container's
single IP, so an IP-keyed rate limiter would just 429 the entire sitemap
render on post-deploy cache-miss bursts. The cache collapses the cost
ceiling to one materialization for the cache TTL across all Gunicorn
workers, which is the workload we actually care about bounding.
"""

from __future__ import annotations

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from ninja import Router

from apps.core.api.sitemap_schemas import (
    SitemapEntrySchema,
    SitemapFeedSchema,
    SitemapResponseSchema,
)
from apps.core.sitemap import all_sitemap_feeds

sitemap_router = Router()

SITEMAP_CACHE_KEY = "core:sitemap:feeds"
SITEMAP_CACHE_TTL = 3600  # seconds


def _build_response() -> SitemapResponseSchema:
    feeds = all_sitemap_feeds()
    return SitemapResponseSchema(
        feeds=[
            SitemapFeedSchema(
                kind=f.kind,
                entries=[
                    SitemapEntrySchema(slug=e.slug, lastmod=e.lastmod)
                    for e in f.entries
                ],
                detail_excluded_slugs=sorted(f.detail_excluded_slugs),
                max_lastmod=f.max_lastmod,
            )
            for f in feeds
        ]
    )


@sitemap_router.get("", response=SitemapResponseSchema)
def get_sitemap(request: HttpRequest, response: HttpResponse) -> SitemapResponseSchema:
    """Return every ``SitemappedModel`` feed in a single payload.

    Cached process-wide for ``SITEMAP_CACHE_TTL`` seconds. ``Cache-Control``
    asks downstream callers (the SvelteKit endpoint, crawlers if exposed
    directly) to cache for the same window.
    """
    cached: SitemapResponseSchema | None = cache.get(SITEMAP_CACHE_KEY)
    if cached is None:
        cached = _build_response()
        cache.set(SITEMAP_CACHE_KEY, cached, SITEMAP_CACHE_TTL)
    response["Cache-Control"] = f"public, max-age={SITEMAP_CACHE_TTL}"
    return cached
