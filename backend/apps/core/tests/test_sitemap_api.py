"""Tests for ``GET /api/sitemap/``."""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache
from django.test import Client

from apps.catalog.models import MachineModel, Title
from apps.core.api.sitemap import SITEMAP_CACHE_KEY, SITEMAP_CACHE_TTL


@pytest.fixture(autouse=True)
def clear_sitemap_cache():
    """Wipe the sitemap cache key between tests so the cache state from
    one test never leaks into another."""
    cache.delete(SITEMAP_CACHE_KEY)
    yield
    cache.delete(SITEMAP_CACHE_KEY)


@pytest.mark.django_db
class TestSitemapEndpoint:
    def setup_method(self) -> None:
        self.client = Client()

    def test_returns_200_with_feed_shape(self) -> None:
        title = Title.objects.create(name="Solo", slug="solo")
        MachineModel.objects.create(title=title, name="Solo", slug="solo-model")

        resp = self.client.get("/api/sitemap/")
        assert resp.status_code == 200, resp.content
        body = json.loads(resp.content)

        feeds_by_kind = {f["kind"]: f for f in body["feeds"]}
        assert "title" in feeds_by_kind
        assert "model" in feeds_by_kind

        title_feed = feeds_by_kind["title"]
        assert set(title_feed.keys()) == {
            "kind",
            "entries",
            "detail_excluded_slugs",
            "max_lastmod",
        }
        assert title_feed["entries"][0]["slug"] == "solo"
        assert "lastmod" in title_feed["entries"][0]
        assert title_feed["max_lastmod"] is not None

    def test_machine_model_non_canonical_included(self) -> None:
        """Single-Model-Title rule: the Model slug appears in
        ``detail_excluded_slugs`` on the ``model`` feed."""
        title = Title.objects.create(name="Only", slug="only")
        MachineModel.objects.create(title=title, name="Only", slug="only-model")

        resp = self.client.get("/api/sitemap/")
        assert resp.status_code == 200
        feeds_by_kind = {f["kind"]: f for f in json.loads(resp.content)["feeds"]}
        assert "only-model" in feeds_by_kind["model"]["detail_excluded_slugs"]

    def test_sets_cache_control_header(self) -> None:
        Title.objects.create(name="Solo", slug="solo")
        resp = self.client.get("/api/sitemap/")
        assert resp["Cache-Control"] == f"public, max-age={SITEMAP_CACHE_TTL}"

    def test_second_request_hits_cache(self, monkeypatch) -> None:
        """A second request within the TTL is served from cache —
        ``all_sitemap_feeds()`` runs exactly once across two GETs."""
        Title.objects.create(name="A", slug="a")

        call_count = {"n": 0}
        import apps.core.api.sitemap as sitemap_module

        real_all = sitemap_module.all_sitemap_feeds

        def counting_all():
            call_count["n"] += 1
            return real_all()

        monkeypatch.setattr(sitemap_module, "all_sitemap_feeds", counting_all)

        r1 = self.client.get("/api/sitemap/")
        r2 = self.client.get("/api/sitemap/")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.content == r2.content
        assert call_count["n"] == 1, (
            f"expected one materialization across two requests; got {call_count['n']}"
        )
