"""Wire schemas for the sitemap API.

Decoupled from ``apps.core.sitemap`` so the derivation module can stay
free of Ninja / Pydantic imports and be unit-tested without the API
machinery.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema


class SitemapEntrySchema(Schema):
    """One URL's identifying slug + ``lastmod`` for a sitemap feed.

    ``lastmod`` is serialized as ISO 8601 — the SvelteKit consumer passes
    the string straight through to super-sitemap.
    """

    slug: str
    lastmod: datetime


class SitemapFeedSchema(Schema):
    """All sitemap entries for one entity ``kind``.

    ``detail_excluded_slugs`` is the subset whose ``catalog-detail`` URL is
    non-canonical and must be omitted from detail-route emissions; their
    ``/edit-history`` and ``/sources`` URLs are still expected to render
    (the slugs stay in ``entries``).
    """

    kind: str
    entries: list[SitemapEntrySchema]
    detail_excluded_slugs: list[str]
    max_lastmod: datetime | None


class SitemapResponseSchema(Schema):
    feeds: list[SitemapFeedSchema]
