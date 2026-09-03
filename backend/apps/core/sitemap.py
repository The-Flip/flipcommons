"""Derive sitemap feeds by walking the ``SitemappedModel`` registry.

Mirrors the same ``apps.get_models()`` + ``issubclass`` walk as
``apps/core/entity_types.py``. Each concrete ``SitemappedModel`` subclass
contributes one ``SitemapFeed``; per-model behavior (which rows are
included and their ``lastmod``) is driven by
``SitemappedModel.sitemap_queryset()``. A ``LinkableModel`` that is not a
``SitemappedModel`` (linkable but not in the sitemap) is excluded.

The endpoint that ships this over the wire lives at
``apps/core/api/sitemap.py``; this module is pure derivation so it can be
unit-tested without hitting Django's URL resolver or Ninja.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from django.apps import apps
from django.db.models.query import EmptyQuerySet

from apps.core.models import SitemappedModel


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

    ``max_lastmod`` is the newest ``lastmod`` across ``entries`` — used by
    the SvelteKit endpoint for sitemap-index ``<lastmod>`` values when the
    feed is paginated.
    """

    kind: str
    entries: list[SitemapEntry]
    max_lastmod: datetime | None


def all_sitemap_feeds() -> list[SitemapFeed]:
    """Build one ``SitemapFeed`` per concrete ``SitemappedModel`` subclass.

    Skips feeds with zero entries (so ``max_lastmod`` is always a real
    datetime when a feed is returned). Entries whose ``_last_modified``
    annotation evaluates to ``None`` are dropped — that's the legitimate
    aggregation case (a future ``Max("…__updated_at")`` over an empty
    relation, etc.). A model whose override forgot to
    ``.annotate(_last_modified=…)`` raises ``FieldError`` when the query is
    built, so the contract is enforced by failure rather than by silently
    producing an empty feed.

    Reads two columns per row rather than model instances: a feed needs only
    the public id and the freshness value, and building an instance per row
    costs more than the query that fetched it.
    """
    feeds: list[SitemapFeed] = []
    for model in apps.get_models():
        if not issubclass(model, SitemappedModel) or model._meta.abstract:
            continue
        queryset = model.sitemap_queryset()
        # ``cls.objects.none()`` is the documented way to opt out, and it
        # carries no ``_last_modified`` annotation — naming the column below
        # would raise ``FieldError`` while resolving the query rather than
        # yielding the zero rows the override asked for.
        if isinstance(queryset, EmptyQuerySet):
            continue
        rows = queryset.values_list(model.public_id_field, "_last_modified")
        entries = [
            SitemapEntry(public_id, lastmod)
            for public_id, lastmod in rows.iterator()
            if lastmod is not None
        ]
        if not entries:
            continue
        feeds.append(
            SitemapFeed(
                kind=model.entity_type,
                entries=entries,
                max_lastmod=max(e.lastmod for e in entries),
            )
        )
    return feeds
