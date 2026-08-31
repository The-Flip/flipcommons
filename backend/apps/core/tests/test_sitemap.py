"""Tests for ``apps.core.sitemap.all_sitemap_feeds()`` and the underlying
``SitemappedModel`` sitemap classmethods.

Mirrors the registry-walk shape from ``apps.core.entity_types`` — adding a
new ``SitemappedModel`` automatically picks up the parameterized parity
checks below.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from django.apps import apps
from django.core.exceptions import FieldError

from apps.catalog.models import Title
from apps.core.models import SitemappedModel
from apps.core.sitemap import (
    SitemapEntry,
    SitemapFeed,
    all_sitemap_feeds,
)


def _concrete_sitemapped_models() -> list[type[SitemappedModel]]:
    return [
        cls
        for cls in apps.get_models()
        if issubclass(cls, SitemappedModel) and not cls._meta.abstract
    ]


# ---------------------------------------------------------------------------
# Per-model default behavior (parameterized over every SitemappedModel)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model",
    _concrete_sitemapped_models(),
    ids=lambda m: m.__name__,
)
class TestPerModelDefaults:
    """Parity checks fired once per concrete ``SitemappedModel`` subclass."""

    def test_sitemap_queryset_returns_queryset(self, model):
        qs = model.sitemap_queryset()
        # Cheap structural check that the queryset is annotated correctly.
        assert "_last_modified" in qs.query.annotations

    def test_sitemap_queryset_excludes_deleted_rows(self, model):
        """Default ``sitemap_queryset()`` calls ``.active()`` — no
        ``status='deleted'`` row should appear."""
        statuses = list(model.sitemap_queryset().values_list("status", flat=True))
        assert "deleted" not in statuses

    def test_non_canonical_default_iterable(self, model):
        """The default ``non_canonical_detail_slugs()`` (and any override)
        returns something the sitemap can wrap in ``frozenset(...)``."""
        result = frozenset(model.non_canonical_detail_slugs())
        assert isinstance(result, frozenset)


# ---------------------------------------------------------------------------
# all_sitemap_feeds() shape + behavior
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAllSitemapFeeds:
    def test_empty_database_returns_no_feeds(self):
        """With no rows in any SitemappedModel table, no feed is emitted."""
        feeds = all_sitemap_feeds()
        assert feeds == []

    def test_feed_for_populated_model(self):
        """A populated Title produces a feed with one entry."""
        Title.objects.create(name="Solo", slug="solo")
        feeds = {f.kind: f for f in all_sitemap_feeds()}
        assert "title" in feeds
        title_feed = feeds["title"]
        assert len(title_feed.entries) == 1
        entry = title_feed.entries[0]
        assert isinstance(entry, SitemapEntry)
        assert entry.slug == "solo"
        assert isinstance(entry.lastmod, datetime)
        assert title_feed.max_lastmod == entry.lastmod

    def test_detail_excluded_slugs_is_frozenset(self):
        """``detail_excluded_slugs`` is always a ``frozenset`` (default
        empty), regardless of whether the model overrides
        ``non_canonical_detail_slugs()``."""
        Title.objects.create(name="A", slug="a")
        feeds = all_sitemap_feeds()
        for feed in feeds:
            assert isinstance(feed, SitemapFeed)
            assert isinstance(feed.detail_excluded_slugs, frozenset)

    def test_entries_ordered_by_public_id(self):
        """Default ``sitemap_queryset()`` orders by ``public_id_field``."""
        Title.objects.create(name="B", slug="b-title")
        Title.objects.create(name="A", slug="a-title")
        Title.objects.create(name="C", slug="c-title")

        feeds = {f.kind: f for f in all_sitemap_feeds()}
        slugs = [e.slug for e in feeds["title"].entries]
        assert slugs == sorted(slugs)

    def test_deleted_rows_excluded_from_feed(self):
        """Soft-deleted rows are absent from the feed entries."""
        Title.objects.create(name="Live", slug="live")
        Title.objects.create(name="Dead", slug="dead", status="deleted")

        feeds = {f.kind: f for f in all_sitemap_feeds()}
        slugs = {e.slug for e in feeds["title"].entries}
        assert "live" in slugs
        assert "dead" not in slugs

    def test_machine_model_non_canonical_carried_through(self):
        """A single-Model Title's MachineModel slug appears in
        ``detail_excluded_slugs`` on the ``model`` feed."""
        from apps.catalog.models import MachineModel

        title = Title.objects.create(name="Only", slug="only-title")
        MachineModel.objects.create(title=title, name="Only", slug="only-model")

        feeds = {f.kind: f for f in all_sitemap_feeds()}
        model_feed = feeds["model"]
        assert "only-model" in model_feed.detail_excluded_slugs
        # The entry is still in `entries` so /edit-history and /sources emit.
        assert any(e.slug == "only-model" for e in model_feed.entries)

    def test_max_lastmod_matches_newest_entry(self):
        Title.objects.create(name="A", slug="a")
        Title.objects.create(name="B", slug="b")

        feeds = {f.kind: f for f in all_sitemap_feeds()}
        title_feed = feeds["title"]
        assert title_feed.max_lastmod == max(e.lastmod for e in title_feed.entries)


# ---------------------------------------------------------------------------
# Opt-out path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSitemapOptOut:
    """A model whose ``sitemap_queryset()`` returns ``.none()`` produces no
    feed — even if rows exist in the table."""

    def test_none_queryset_produces_no_feed(self, monkeypatch):
        Title.objects.create(name="A", slug="a")

        # Force Title to opt out by returning an empty queryset.
        monkeypatch.setattr(
            Title,
            "sitemap_queryset",
            classmethod(lambda cls: cls.objects.none()),
        )

        feeds = {f.kind: f for f in all_sitemap_feeds()}
        assert "title" not in feeds

    def test_unannotated_queryset_raises(self, monkeypatch):
        """An override returning rows but no ``_last_modified`` is a
        programmer error, and must fail loudly rather than quietly drop the
        model's URLs out of the sitemap.

        The opt-out above and this case differ only by whether the queryset
        is empty, so they are easy to conflate — pin both.
        """
        Title.objects.create(name="A", slug="a")

        monkeypatch.setattr(
            Title,
            "sitemap_queryset",
            classmethod(lambda cls: cls.objects.all()),
        )

        with pytest.raises(FieldError, match="_last_modified"):
            all_sitemap_feeds()
