"""Caddy must redirect non-asset paths on the static CDN hostname to the apex.

The ``static.flipcommons.org`` pull zone proxies every path to its origin, so
without this block it serves the whole site as crawlable HTML on a second
hostname. Nothing about the block is observable from the application, so these
assertions pin it.

Two choices are deliberate. No ``X-Origin-Auth`` interlock, because the target
is the apex and cannot loop the way ``@direct_origin``'s could. An exact asset
allowlist, because browsers reject module scripts and fonts redirected
cross-origin, so a missing prefix is an outage; the last test cross-checks the
allowlist against every asset reference in ``app.html``.
"""

from __future__ import annotations

import re

from django.conf import settings

STATIC_HOST = "static.flipcommons.org"

# What docs/Hosting.md § Static edge cache says the zone exists to serve.
EXPECTED_ASSET_PATHS = frozenset(
    {"/_app/*", "/fonts/*", "/images/*", "/apple-touch-icon.png"}
)

# Files under frontend/static/ that are only ever referenced root-relative, so
# they load from the apex and the static host may redirect them.
APEX_ONLY_STATIC_PATHS = frozenset({"/site.webmanifest", "/fakes/*"})

_ROOT = settings.BASE_DIR.parent


def _caddyfile() -> str:
    return (_ROOT / "Caddyfile").read_text()


def _static_block() -> str:
    match = re.search(
        r"^@static_non_asset \{\n(.*?)^\}", _caddyfile(), re.MULTILINE | re.DOTALL
    )
    assert match, "Caddyfile must define a @static_non_asset matcher block"
    return match.group(1)


def _allowlisted_paths() -> list[str]:
    match = re.search(r"^\s*not path\s+(.+?)\s*$", _static_block(), re.MULTILINE)
    assert match, (
        "@static_non_asset must exclude the asset paths with one `not path` line"
    )
    return match.group(1).split()


def _covers(pattern: str, path: str) -> bool:
    """Whether a Caddy ``path`` argument matches ``path``: exact, or prefix with ``*``."""
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    return path == pattern


def test_matcher_names_the_static_hostname() -> None:
    assert re.search(
        rf"^\s*host\s+{re.escape(STATIC_HOST)}\s*$", _static_block(), re.MULTILINE
    ), f"@static_non_asset must match the static CDN hostname {STATIC_HOST}"


def test_matcher_excludes_exactly_the_asset_paths() -> None:
    assert set(_allowlisted_paths()) == EXPECTED_ASSET_PATHS, (
        "@static_non_asset must exclude exactly the asset paths the static zone "
        f"serves, got {_allowlisted_paths()}; a broader entry such as /about/* "
        "would pass HTML routes through on the static host"
    )


def test_matcher_has_no_origin_auth_interlock() -> None:
    assert "X-Origin-Auth" not in _static_block(), (
        "@static_non_asset must not test X-Origin-Auth: its target is the apex, so "
        "it cannot loop, and the static zone sends no such header"
    )


def test_non_asset_paths_redirect_permanently_to_the_public_origin() -> None:
    match = re.search(
        r"^handle @static_non_asset \{\n\s*redir\s+(\S+)\s+(\S+)\s*$",
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must define a handle @static_non_asset containing a redir"
    target, permanence = match.groups()
    assert target == "https://flipcommons.org{uri}", (
        f"static-host pages must redirect to the public origin, got {target!r}"
    )
    assert permanence == "permanent", (
        f"the redirect must be a 301 so search engines consolidate, got {permanence!r}"
    )


def test_the_redirect_is_not_cacheable() -> None:
    match = re.search(
        r'^header\s+@static_non_asset\s+Cache-Control\s+"([^"]+)"\s*$',
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must set Cache-Control on the @static_non_asset matcher"
    assert "no-store" in match.group(1), (
        "the redirect must be uncacheable: the static zone has Follow Redirects off "
        f"and a 30-day default TTL, got {match.group(1)!r}"
    )


def test_the_redirect_is_handled_before_the_upstream_proxies() -> None:
    caddyfile = _caddyfile()
    static = caddyfile.find("handle @static_non_asset {")
    django = caddyfile.find("handle @django {")
    assert static != -1, "Caddyfile must define a handle @static_non_asset"
    assert django != -1, "Caddyfile must define a handle @django"
    assert static < django, (
        "handle @static_non_asset must precede handle @django: Caddy runs only the "
        "first matching handle, so a later block would let static-host /api/ "
        "requests reach Django"
    )


def test_every_asset_reference_in_app_html_is_allowlisted() -> None:
    app_html = (_ROOT / "frontend" / "src" / "app.html").read_text()
    references = re.findall(r"%sveltekit\.assets%(/[^\"'\s]+)", app_html)
    assert references, (
        "app.html should reference at least one asset via %sveltekit.assets%"
    )
    allowlist = _allowlisted_paths()
    uncovered = [
        ref
        for ref in references
        if not any(_covers(pattern, ref) for pattern in allowlist)
    ]
    assert not uncovered, (
        f"app.html references {uncovered} through the assets path but "
        f"@static_non_asset only excludes {allowlist}; extend the `not path` allowlist"
    )


def test_every_static_dir_entry_is_allowlisted_or_declared_apex_only() -> None:
    """``asset()`` can point at anything under frontend/static/, not only app.html."""
    static_dir = _ROOT / "frontend" / "static"
    entries = [
        f"/{entry.name}/*" if entry.is_dir() else f"/{entry.name}"
        for entry in static_dir.iterdir()
    ]
    known = set(_allowlisted_paths()) | APEX_ONLY_STATIC_PATHS
    unknown = sorted(set(entries) - known)
    assert not unknown, (
        f"frontend/static/ has {unknown}, which @static_non_asset neither excludes "
        "nor APEX_ONLY_STATIC_PATHS declares apex-only; on the static host it would "
        "be redirected. Move it under /images/, extend the `not path` allowlist, or "
        "declare it apex-only"
    )
