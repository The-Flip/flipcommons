"""Tests for ``GET /api/sitemap/``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client

from apps.catalog.models import MachineModel, Title
from apps.core.api.sitemap import SITEMAP_CACHE_KEY, SITEMAP_CACHE_TTL, _lastmod


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
        MachineModel.objects.create(title=title, name="Solo LE", slug="solo-le")

        resp = self.client.get("/api/sitemap/")
        assert resp.status_code == 200, resp.content
        body = json.loads(resp.content)

        feeds_by_kind = {f["kind"]: f for f in body["feeds"]}
        assert "title" in feeds_by_kind
        assert "model" in feeds_by_kind

        title_feed = feeds_by_kind["title"]
        assert set(title_feed.keys()) == {"kind", "entries", "max_lastmod"}
        assert title_feed["entries"][0]["slug"] == "solo"
        assert "lastmod" in title_feed["entries"][0]
        assert title_feed["max_lastmod"] is not None

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

    def test_caches_serialized_bytes_not_an_object_graph(self) -> None:
        """The cache holds the encoded response, so a hit costs one read.

        Caching a ``SitemapResponseSchema`` instead would leave every request
        unpickling an object per entry and re-encoding it to these same bytes —
        which no other assertion here would notice, because the response would
        look identical. This is the one test that pins the storage format.
        """
        Title.objects.create(name="Solo", slug="solo")

        resp = self.client.get("/api/sitemap/")

        cached = cache.get(SITEMAP_CACHE_KEY)
        assert isinstance(cached, tuple), f"expected (bytes, etag); got {type(cached)}"
        json_bytes, etag = cached
        assert isinstance(json_bytes, bytes)
        assert isinstance(etag, str)
        # The served body IS the cached value — nothing re-encodes it per request.
        assert json_bytes == resp.content
        assert resp["ETag"] == etag

    def test_conditional_request_returns_304(self) -> None:
        """The cached ETag is the one served, so ``If-None-Match`` still matches.

        ``ConditionalGetMiddleware`` would synthesize an ETag on its own; this
        guards that serving a cached one keeps conditional requests working.
        """
        Title.objects.create(name="Solo", slug="solo")

        first = self.client.get("/api/sitemap/")
        etag = first["ETag"]
        assert etag

        second = self.client.get("/api/sitemap/", headers={"if-none-match": etag})
        assert second.status_code == 304
        assert second.content == b""


class TestLastmodWireFormat:
    """``_lastmod`` formats every entry's datetime during the build instead of
    leaving it to the JSON encoder's ``default`` hook, so its output has to stay
    byte-identical to what ``DjangoJSONEncoder`` would have written.
    """

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(
                datetime(2026, 5, 7, 17, 54, 12, 109000, tzinfo=UTC), id="milliseconds"
            ),
            pytest.param(
                datetime(2026, 5, 7, 17, 54, 12, tzinfo=UTC), id="whole-second"
            ),
            pytest.param(
                datetime(2026, 1, 1, 0, 0, 0, 1, tzinfo=UTC), id="one-microsecond"
            ),
            pytest.param(
                datetime(
                    2026, 5, 7, 17, 54, 12, 109000, tzinfo=timezone(timedelta(hours=-5))
                ),
                id="non-utc-offset",
            ),
        ],
    )
    def test_matches_django_json_encoder(self, value: datetime) -> None:
        assert _lastmod(value) == DjangoJSONEncoder().default(value)
