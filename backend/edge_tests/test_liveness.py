"""Does the deployed site actually render?

Every other check here would pass against a site whose pages return 500, since
Caddy emits its headers long before SvelteKit decides it cannot render.
"""

from __future__ import annotations

import httpx

from edge_tests.probe import html_title


def test_django_is_reachable_through_caddy(edge: httpx.Client) -> None:
    """``/__health`` is answered by Node; this asks for a route Django serves."""
    response = edge.get("/api/health")
    assert response.status_code == 200


def test_homepage_renders(edge: httpx.Client) -> None:
    response = edge.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert html_title(response)


def test_catalog_detail_page_renders(
    edge: httpx.Client, catalog_detail_path: str
) -> None:
    """A detail page is the deepest read path: SSR, the API hop and the DB."""
    response = edge.get(catalog_detail_path)
    assert response.status_code == 200, (
        f"{catalog_detail_path} came back {response.status_code}; the sitemap "
        "advertises it, so either it renders or the sitemap is lying"
    )
    assert response.headers["content-type"].startswith("text/html")
    assert html_title(response)
