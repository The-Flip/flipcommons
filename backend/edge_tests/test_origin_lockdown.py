"""The Railway origin must be reachable only through Bunny.

A caller that reaches the container directly has bypassed the edge cache, its
rate limits and its Edge Rules, whatever Host it wears. Only a live request can
show whether the deployed container's `ORIGIN_SHARED_SECRET` matches what Bunny
sends; a wrong-but-well-formed value passes `check --deploy` and boots cleanly.

Every case here is a negative one. The positive case is the only one that would
need the production secret, and the site being up already proves it.
"""

from __future__ import annotations

import httpx


def _served_no_page(response: httpx.Response) -> bool:
    """Whether the response withheld actual site content, not merely a status."""
    return "<html" not in response.text.lower()


class TestDirectOriginAccess:
    def test_no_auth_header_is_redirected_to_the_apex(
        self, origin: httpx.Client, edge_base_url: str
    ) -> None:
        """A 301 rather than a 403, so the signal crawlers accrued on this
        hostname moves to the apex rather than being discarded.
        """
        response = origin.get("/models/")
        assert response.status_code == 301
        assert response.headers["location"] == f"{edge_base_url}/models/"
        assert _served_no_page(response)

    def test_a_wrong_secret_is_refused(self, origin: httpx.Client) -> None:
        """`@direct_origin` tests for the header's ABSENCE, so any value here
        routes the request past it into `@unauthenticated`, which compares it.
        """
        response = origin.get("/", headers={"X-Origin-Auth": "not-the-secret"})
        assert response.status_code == 403
        assert _served_no_page(response)

    def test_healthcheck_host_exemption_is_scoped_to_the_probe_path(
        self, origin: httpx.Client
    ) -> None:
        """Drop the path condition and one spoofed header opens the whole site."""
        response = origin.get("/", headers={"Host": "healthcheck.railway.app"})
        assert response.status_code != 200, (
            "spoofing Host: healthcheck.railway.app served a page; the gate's "
            "exemption is no longer paired with the /__health path"
        )
        assert _served_no_page(response)


def test_www_redirects_to_the_apex(www: httpx.Client, edge_base_url: str) -> None:
    """Bunny's cache key excludes the hostname, so without the redirect rule a
    `www` request for a cached path is answered with the apex's copy.
    """
    response = www.get("/about")
    assert response.status_code == 301
    assert response.headers["location"] == f"{edge_base_url}/about"
