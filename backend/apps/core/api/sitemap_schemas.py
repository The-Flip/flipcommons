"""Wire schemas for the sitemap API, plus their plain-dict twins.

Decoupled from ``apps.core.sitemap`` so the derivation module can stay
free of Ninja / Pydantic imports and be unit-tested without the API
machinery.

The ``*Schema`` classes declare the contract OpenAPI and the frontend codegen
read. The ``*Dict`` twins name the shape the endpoint actually assembles: the
response cache encodes with ``json.dumps``, so the payload has to be plain
dicts, and naming them keeps that assembly from being typed as a faceless
``dict[str, object]``. ``set_cached_response`` still validates the whole
payload against ``SitemapResponseSchema`` in DEBUG, which is what keeps the
two definitions honest.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

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


class SitemapEntryDict(TypedDict):
    """Plain-dict twin of :class:`SitemapEntrySchema`.

    ``lastmod`` is a ``str`` rather than a ``datetime``: the payload is built
    already-serialized, so the JSON encoder never has to format it.
    """

    slug: str
    lastmod: str


class SitemapFeedDict(TypedDict):
    """Plain-dict twin of :class:`SitemapFeedSchema`."""

    kind: str
    entries: list[SitemapEntryDict]
    detail_excluded_slugs: list[str]
    max_lastmod: str | None


class SitemapPayloadDict(TypedDict):
    """Plain-dict twin of :class:`SitemapResponseSchema`."""

    feeds: list[SitemapFeedDict]
