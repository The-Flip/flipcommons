"""Do conditional requests survive the round trip through the edge?

Bunny terminates them itself: when it holds a copy it compares the tag and
synthesizes the ``304``, and when it holds none it drops ``If-None-Match`` and
the origin serves a full ``200`` whatever the origin's own conditional support.
So a ``304`` here is evidence the edge holds a copy and a ``200`` is evidence it
does not. These tests ask that of one path in each state.
"""

from __future__ import annotations

import httpx
import pytest

from edge_tests.probe import cdn_cache

# One entity is enough. Every export route is registered from a single closure
# in apps/catalog/api/export.py, so the others exercise identical code.
EXPORT_PATH = "/api/public/export/models/"


def test_export_conditional_get_returns_304(edge: httpx.Client) -> None:
    """Holding the export takes a cacheable ``Cache-Control`` from the origin
    and an exemption from the "Bypass API" Edge Rule in the Bunny dashboard.
    The first two assertions say which half is missing.

    Streamed and never read: only the headers matter, and this is the largest
    response the site serves.
    """
    with edge.stream("GET", EXPORT_PATH) as first:
        assert first.status_code == 200
        assert "s-maxage" in first.headers.get("Cache-Control", ""), (
            f"Cache-Control is {first.headers.get('Cache-Control')!r}; the origin "
            "is not marking the export edge-cacheable, so Bunny may never hold a "
            "copy whatever its rules say"
        )
        assert cdn_cache(first) != "BYPASS", (
            "the export is still bypassing the edge; the Match none URL trigger "
            "for */api/public/* on the Bypass API rule is missing or has drifted"
        )
        etag = first.headers.get("ETag")
        assert etag, (
            "no ETag on the bulk export; apps.core.response_cache sets one on "
            "every cached response, so something between Django and here "
            "stripped it"
        )

    with edge.stream("GET", EXPORT_PATH, headers={"If-None-Match": etag}) as second:
        assert second.status_code == 304, (
            f"re-requested with If-None-Match: {etag} and got "
            f"{second.status_code}; the full payload ships on every request"
        )


def test_sitemap_conditionals_are_answered_by_the_edge(edge: httpx.Client) -> None:
    """The ``304`` is Bunny's, from its held copy; the origin never sees the tag."""
    first = edge.get("/sitemap.xml")
    assert first.status_code == 200
    etag = first.headers.get("ETag")
    if not etag:
        pytest.skip("no ETag on /sitemap.xml; nothing to make conditional")

    second = edge.get("/sitemap.xml", headers={"If-None-Match": etag})
    assert second.status_code == 304, (
        f"re-requested /sitemap.xml with If-None-Match: {etag} and got "
        f"{second.status_code} ({second.headers.get('cdn-cache')}); Bunny is no "
        "longer answering conditionals from a held copy of the sitemap. Look at "
        "the sitemap's Cache-Control and the zone's cache settings, not at the "
        "SvelteKit handler, which never receives the client's condition"
    )
