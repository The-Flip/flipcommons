"""The Bunny apex zone's Edge Rules, which live in a dashboard and in no repo.

Nothing in this repository can express these rules, review them or notice them
changing, so these tests are the closest thing to a lockfile the zone has.
"""

from __future__ import annotations

import httpx

from edge_tests.probe import cdn_cache

# The apex pull zone (`flipcommons-html`). The DNS `PZ` record names a zone by
# id, so pointing it at a different one passes every DNS check while silently
# dropping the origin config and every Edge Rule with it.
APEX_PULL_ZONE_ID = "5969801"


class TestApiBypass:
    """The public API is the only `/api/` path the edge may hold."""

    def test_internal_api_bypasses(self, edge: httpx.Client) -> None:
        response = edge.get("/api/health")
        assert cdn_cache(response) == "BYPASS", (
            "an internal API response was cached at the edge; the Match none "
            "carve-out on the Bypass API rule is wider than */api/public/*"
        )

    def test_kiosk_public_api_bypasses(self, edge: httpx.Client) -> None:
        """A kiosk dump carries show-all content. The kiosk rule keys on the
        cookie and an asset list, not the path, so the cheap filter query
        proves the carve-out without a cold export build at the origin."""
        response = edge.get(
            "/api/public/filter/models/?year_min=1990",
            headers={"Cookie": "mode=kiosk"},
        )
        assert cdn_cache(response) == "BYPASS", (
            "a kiosk public API response was served from the shared edge cache; "
            "the kiosk rule's Match none list has grown past assets"
        )


class TestSignedInBypass:
    """A `sessionid` cookie must bypass HTML, but must NOT bypass assets."""

    def test_html_bypasses_for_a_session_cookie(self, edge: httpx.Client) -> None:
        response = edge.get("/about", headers={"Cookie": "sessionid=probe"})
        assert cdn_cache(response) == "BYPASS", (
            "a signed-in HTML request was served from the shared edge cache; a "
            "contributor can be shown a stale copy of their own edit"
        )

    def test_assets_do_not_bypass_for_a_session_cookie(
        self, edge: httpx.Client
    ) -> None:
        response = edge.get("/_app/version.json", headers={"Cookie": "sessionid=probe"})
        assert cdn_cache(response) != "BYPASS", (
            "assets are bypassing the cache for signed-in visitors; the Match "
            "none URL carve-out on the bypass rule is missing or has drifted"
        )


class TestKioskBypass:
    """The kiosk cookie must bypass; `?mode=kiosk` must not."""

    def test_kiosk_cookie_bypasses(self, edge: httpx.Client) -> None:
        response = edge.get("/", headers={"Cookie": "mode=kiosk"})
        assert cdn_cache(response) == "BYPASS", (
            "a kiosk request was cached at the edge; unlicensed content can "
            "now be served to public visitors"
        )

    def test_kiosk_query_string_is_an_ordinary_request(
        self, edge: httpx.Client
    ) -> None:
        response = edge.get("/?mode=kiosk")
        assert cdn_cache(response) != "BYPASS", (
            "?mode=kiosk is bypassing the cache; the kiosk rule is keyed on the "
            "query string rather than (or as well as) the cookie"
        )


def test_health_probe_is_never_served_from_cache(edge: httpx.Client) -> None:
    """Uptime monitoring has to see the origin's current state."""
    response = edge.get("/__health")
    assert response.json()["status"] != "error"
    assert "no-store" in response.headers.get("Cache-Control", "")
    assert cdn_cache(response) != "HIT", (
        "the liveness probe was answered from the edge cache; monitoring is "
        "reporting a cached verdict rather than the origin's"
    )


def test_apex_is_served_by_the_expected_pull_zone(edge: httpx.Client) -> None:
    response = edge.get("/__health")
    assert response.headers.get("cdn-pullzone") == APEX_PULL_ZONE_ID, (
        f"served by pull zone {response.headers.get('cdn-pullzone')}, expected "
        f"{APEX_PULL_ZONE_ID}: the DNS PZ record points at a different zone, "
        "which silently drops the origin config and every Edge Rule with it"
    )
