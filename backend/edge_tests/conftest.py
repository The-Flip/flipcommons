"""Live smoke tests against the deployed site, through the Bunny edge.

The only tests in this project that leave the machine. They exist because the
serving path's behavior is composed by the SvelteKit cache-control hook, Caddy
and the Bunny pull zone's Edge Rules, and every other test terminates at or
below Caddy. ``docs/Hosting.md`` has what the suite covers and when to run it.

Constraints on anything added here:

- ``GET`` and ``HEAD`` only. These run against production.
- Every request goes through ``probe.client_for``, whose user-agent keeps a run
  out of the production log analytics.
- Discover targets from the sitemap. A pinned slug goes red on a rename, which
  teaches people to ignore red.
- Assert structure, never copy.
- No ``xfail``. A human reads this after a deploy, so a red line is the record
  of a live bug.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from typing import Final
from urllib.parse import urlparse, urlunparse

import httpx
import pytest

from edge_tests.probe import client_for

DEFAULT_EDGE_BASE_URL: Final = "https://flipcommons.org"
DEFAULT_ORIGIN_BASE_URL: Final = "https://flipcommons-production.up.railway.app"

# Pattern rather than an XML parser: this samples one URL out of a document our
# own server generated, so nothing rests on its correctness. A real parser would
# mean an XML-attack-hardened dependency for a fixture, or a lint suppression.
_LOC_RE: Final = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)


@pytest.fixture(scope="session")
def edge_base_url() -> str:
    """The public site, as visitors reach it: through the Bunny apex zone."""
    return os.environ.get("EDGE_BASE_URL", DEFAULT_EDGE_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def origin_base_url() -> str:
    """The Railway container's own hostname, which Bunny pulls from."""
    return os.environ.get("EDGE_ORIGIN_BASE_URL", DEFAULT_ORIGIN_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def www_base_url(edge_base_url: str) -> str:
    """The ``www`` hostname of whatever site is under test."""
    parsed = urlparse(edge_base_url)
    if parsed.hostname is None or parsed.hostname.startswith("www."):
        pytest.skip(f"{edge_base_url} is already a www host")
    return urlunparse(parsed._replace(netloc=f"www.{parsed.netloc}"))


@pytest.fixture(scope="session")
def edge(edge_base_url: str) -> Iterator[httpx.Client]:
    with client_for(edge_base_url) as client:
        yield client


@pytest.fixture(scope="session")
def origin(origin_base_url: str) -> Iterator[httpx.Client]:
    with client_for(origin_base_url) as client:
        yield client


@pytest.fixture(scope="session")
def www(www_base_url: str) -> Iterator[httpx.Client]:
    with client_for(www_base_url) as client:
        yield client


@pytest.fixture(scope="session", autouse=True)
def _require_live_site(edge: httpx.Client, edge_base_url: str) -> None:
    """Abort the session if the site is not answering at all.

    A total outage would otherwise produce one red line per test, burying the
    single fact worth reading.
    """
    try:
        response = edge.get("/__health")
    except httpx.HTTPError as exc:
        pytest.exit(f"{edge_base_url} is unreachable: {exc}", returncode=1)
    if response.status_code != 200:
        pytest.exit(
            f"{edge_base_url}/__health returned {response.status_code}: the site "
            "is down or not serving. Nothing else in this suite is meaningful.",
            returncode=1,
        )


@pytest.fixture(scope="session")
def catalog_detail_path(edge: httpx.Client) -> str:
    """The path of a live model detail page, discovered from the sitemap."""
    response = edge.get("/sitemap.xml")
    if response.status_code != 200:
        pytest.skip(
            f"/sitemap.xml returned {response.status_code}, so no detail page "
            "could be discovered"
        )

    # The pattern has one capture group, so every match is that group's text.
    locations: list[str] = _LOC_RE.findall(response.text)
    # Past 50,000 URLs the base document becomes a <sitemapindex> whose entries
    # are further sitemaps rather than pages, so follow the first one.
    if "<sitemapindex" in response.text:
        if not locations:
            pytest.skip("/sitemap.xml is an empty sitemapindex")
        locations = _LOC_RE.findall(edge.get(urlparse(locations[0]).path).text)

    for location in locations:
        path = urlparse(location).path
        if path.startswith("/models/") and path.count("/") == 2:
            return path
    pytest.skip("no /models/<slug> URL found in the sitemap")
