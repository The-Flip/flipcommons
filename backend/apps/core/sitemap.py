"""Derive sitemap feeds by walking the ``LinkableModel`` registry.

Mirrors the same ``apps.get_models()`` + ``issubclass`` walk as
``apps/core/entity_types.py``. Each concrete ``LinkableModel`` subclass
contributes one ``SitemapFeed``; per-model behavior (which rows are
included, their ``lastmod``, and which detail URLs are non-canonical) is
driven by ``LinkableModel.sitemap_queryset()`` and
``LinkableModel.non_canonical_detail_slugs()``.

The endpoint that ships this over the wire lives at
``apps/core/api/sitemap.py``; this module is pure derivation so it can be
unit-tested without hitting Django's URL resolver or Ninja.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from django.apps import apps

from apps.core.models import LinkableModel


class SitemapEntry(NamedTuple):
    """One row in a sitemap feed.

    ``slug`` carries whatever the model's ``public_id_field`` produces — a
    plain slug for most entities, a ``/``-separated path for ``Location``
    (``"usa/il/chicago"``). The frontend substitutes it literally into the
    route pattern (``[slug]`` or ``[...path]``).
    """

    slug: str
    lastmod: datetime


class SitemapFeed(NamedTuple):
    """All sitemap entries for one entity ``kind`` (``LinkableModel.entity_type``).

    ``detail_excluded_slugs`` carries the slugs whose ``catalog-detail`` URL
    is non-canonical and must be omitted from the detail-route emissions.
    Their ``/edit-history`` and ``/sources`` URLs are still emitted (the
    entries stay in ``entries``).

    ``max_lastmod`` is the newest ``lastmod`` across ``entries`` — used by
    the SvelteKit endpoint for sitemap-index ``<lastmod>`` values when the
    feed is paginated.
    """

    kind: str
    entries: list[SitemapEntry]
    detail_excluded_slugs: frozenset[str]
    max_lastmod: datetime | None


def all_sitemap_feeds() -> list[SitemapFeed]:
    """Build one ``SitemapFeed`` per concrete ``LinkableModel`` subclass.

    Skips feeds with zero entries (so ``max_lastmod`` is always a real
    datetime when a feed is returned). Entries whose ``_sitemap_lastmod``
    annotation evaluates to ``None`` are dropped — that's the legitimate
    aggregation case (a future ``Max("…__updated_at")`` over an empty
    relation, etc.). A row missing the annotation entirely is a programmer
    bug (override forgot to ``.annotate(_sitemap_lastmod=…)``) and raises
    ``AttributeError`` so it surfaces in CI rather than silently producing
    an empty feed.
    """
    feeds: list[SitemapFeed] = []
    for model in apps.get_models():
        if not issubclass(model, LinkableModel) or model._meta.abstract:
            continue
        slug_field = model.public_id_field
        entries = [
            SitemapEntry(getattr(o, slug_field), lastmod)
            for o in model.sitemap_queryset().iterator()
            # ``_sitemap_lastmod`` is a queryset annotation, not a declared
            # field — read directly so a missing annotation raises (the
            # override contract is enforced by failure, not silent skip).
            if (lastmod := o._sitemap_lastmod) is not None  # type: ignore[attr-defined]
        ]
        if not entries:
            continue
        feeds.append(
            SitemapFeed(
                kind=model.entity_type,
                entries=entries,
                detail_excluded_slugs=frozenset(model.non_canonical_detail_slugs()),
                max_lastmod=max(e.lastmod for e in entries),
            )
        )
    return feeds
