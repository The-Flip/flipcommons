"""The HTTP client and response readers shared by the live edge smoke tests.

Kept out of ``conftest.py`` so importers get a plain module rather than a
pytest plugin.
"""

from __future__ import annotations

import re
from typing import Final

import httpx

# Marks probe traffic in the Bunny and Railway access logs. `production_logs/`
# excludes any `flipcommons-` agent from its health views, so the prefix has to
# survive a rename of the value. A machine key read only by our own pipeline,
# so it carries no contact URL: `http` in an agent also re-buckets its Sentry
# errors as `bot`. See docs/UserAgent.md.
USER_AGENT: Final = "flipcommons-edge-smoke/1.0"

# Generous read timeout: the bulk export is the largest response the site
# serves, and a cold origin has to rebuild it.
TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)

# httpx retries a failed connection, never a completed response.
TRANSPORT_RETRIES: Final = 2

_TITLE_RE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def client_for(base_url: str) -> httpx.Client:
    """A client for one origin, carrying the probe user-agent."""
    return httpx.Client(
        base_url=base_url,
        # Several tests assert on the redirect itself, and following one would
        # silently turn an origin-lockdown check into a fetch of the apex.
        follow_redirects=False,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        transport=httpx.HTTPTransport(retries=TRANSPORT_RETRIES),
    )


def cdn_cache(response: httpx.Response) -> str:
    """Bunny's disposition for this response: HIT, MISS, BYPASS, EXPIRED or STALE.

    A missing header means the response never went through the edge, which is a
    different and larger problem than whichever disposition a caller expected.
    """
    value: str | None = response.headers.get("cdn-cache")
    assert value is not None, (
        f"no `cdn-cache` header on {response.request.url}: this response did not "
        "come through the Bunny edge at all"
    )
    return value.upper()


def html_title(response: httpx.Response) -> str:
    """The page's ``<title>`` text, as the marker that SSR produced a real page."""
    match = _TITLE_RE.search(response.text)
    assert match is not None, f"no <title> element in the response from {response.url}"
    return match.group(1).strip()
