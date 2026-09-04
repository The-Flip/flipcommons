"""Caddy must redirect direct hits on the Railway origin hostname to the apex.

``flipcommons-production.up.railway.app`` serves the same site as the apex and
crawlers indexed it as a duplicate. Nothing about the redirect is observable
from the application, so these assertions pin it.

The ``X-Origin-Auth`` condition is an interlock, not a security control: if
Bunny ever forwards the Railway hostname again, its requests still carry the
header and are excluded rather than redirected into a loop. Testing presence
rather than value keeps a drifted ``ORIGIN_SHARED_SECRET`` from becoming an
outage.
"""

from __future__ import annotations

import re

from django.conf import settings

ORIGIN_HOST = "flipcommons-production.up.railway.app"


def _caddyfile() -> str:
    return (settings.BASE_DIR.parent / "Caddyfile").read_text()


def _direct_origin_block() -> str:
    match = re.search(
        r"^@direct_origin \{\n(.*?)^\}", _caddyfile(), re.MULTILINE | re.DOTALL
    )
    assert match, "Caddyfile must define a @direct_origin matcher block"
    return match.group(1)


def test_matcher_names_the_railway_origin_hostname() -> None:
    assert re.search(
        rf"^\s*host\s+{re.escape(ORIGIN_HOST)}\s*$",
        _direct_origin_block(),
        re.MULTILINE,
    ), f"@direct_origin must match the Railway origin hostname {ORIGIN_HOST}"


def test_matcher_keys_on_the_absence_of_the_cdn_header() -> None:
    assert re.search(
        r"^\s*header\s+!X-Origin-Auth\s*$", _direct_origin_block(), re.MULTILINE
    ), (
        "@direct_origin must match on X-Origin-Auth being absent (`header !X-Origin-Auth`)"
    )


def test_matcher_does_not_compare_the_shared_secret() -> None:
    assert "ORIGIN_SHARED_SECRET" not in _direct_origin_block(), (
        "@direct_origin must test whether X-Origin-Auth exists, not whether it matches "
        "ORIGIN_SHARED_SECRET — a value comparison fails closed, so a drifted or unset "
        "secret would redirect Bunny's own traffic into a loop"
    )


def test_direct_hits_redirect_permanently_to_the_public_origin() -> None:
    match = re.search(
        r"^handle @direct_origin \{\n\s*redir\s+(\S+)\s+(\S+)\s*$",
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must define a handle @direct_origin containing a redir"
    target, permanence = match.groups()
    assert target == "https://flipcommons.org{uri}", (
        f"direct-origin hits must redirect to the public origin, got {target!r}"
    )
    assert permanence == "permanent", (
        f"the redirect must be a 301 so search engines consolidate, got {permanence!r}"
    )


def test_the_redirect_is_not_cacheable() -> None:
    match = re.search(
        r'^header\s+@direct_origin\s+Cache-Control\s+"([^"]+)"\s*$',
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must set Cache-Control on the @direct_origin matcher"
    assert "no-store" in match.group(1), (
        "the redirect must be uncacheable — Bunny applies a 30-day default TTL to any "
        f"response arriving without Cache-Control, got {match.group(1)!r}"
    )


def test_the_redirect_is_handled_before_the_upstream_proxies() -> None:
    caddyfile = _caddyfile()
    direct = caddyfile.find("handle @direct_origin {")
    django = caddyfile.find("handle @django {")
    assert direct != -1, "Caddyfile must define a handle @direct_origin"
    assert django != -1, "Caddyfile must define a handle @django"
    assert direct < django, (
        "handle @direct_origin must precede handle @django: Caddy runs only the first "
        "matching handle in textual order, so a later block would let direct hits on "
        "/api/ and /djadmin/ reach Django instead of redirecting"
    )
