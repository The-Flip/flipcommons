"""Every response leaving the container must carry an explicit ``Cache-Control``.

Bunny gives any response that arrives without one its 30-day zone default.
The SvelteKit hook (``frontend/src/lib/cache-control.server.ts``) stamps
everything it sees, but it never sees prerendered pages, files under
``frontend/static/`` or ``/_app/env.js``; Caddy is the only layer that sees
every response, so it carries a ``?Cache-Control`` default plus per-path
policies for those files.

Every matcher-bound ``Cache-Control`` must use the deferred ``>`` form. A
plain ``header`` runs before ``reverse_proxy``, and the proxy then copies
upstream headers with Add, so on a response the hook also stamped the two
values would stack as two ``Cache-Control`` headers; ``>`` runs the set at
write time and replaces. And a deferred op replaces a plain one that ran
earlier, so a plain ``no-store`` on the gate's 403 or a redirect would be
overwritten by the per-path policy on a font or image URL and cached for
that policy's TTL. Deferred ops unwind in file order, first wins.
"""

from __future__ import annotations

import re

from django.conf import settings

_ROOT = settings.BASE_DIR.parent

# Matchers whose handle proxies to Node, so an upstream Cache-Control can
# arrive and must be replaced rather than stacked.
PROXIED_MATCHERS = ("@fonts", "@version", "@health", "@static_files", "@env")


def _caddyfile() -> str:
    return (_ROOT / "Caddyfile").read_text()


def _path_patterns(matcher: str) -> list[str]:
    match = re.search(rf"^{matcher} path (.+?)\s*$", _caddyfile(), re.MULTILINE)
    assert match, f"Caddyfile must define {matcher} as a path matcher"
    return match.group(1).split()


def _covers(pattern: str, path: str) -> bool:
    """Whether a Caddy ``path`` argument matches ``path``: exact, or prefix with ``*``."""
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    return path == pattern


def _covered(path: str) -> bool:
    patterns = _path_patterns("@static_files") + _path_patterns("@fonts")
    return any(_covers(pattern, path) for pattern in patterns)


def test_site_level_default_is_private_no_store() -> None:
    assert re.search(
        r'^header \?Cache-Control "private, no-store"\s*$', _caddyfile(), re.MULTILINE
    ), (
        'Caddyfile must carry `header ?Cache-Control "private, no-store"`: any '
        "response reaching Bunny without the header inherits a 30-day TTL"
    )


def test_every_static_dir_entry_has_a_policy() -> None:
    """``asset()`` can point at anything under frontend/static/, not only app.html."""
    static_dir = _ROOT / "frontend" / "static"
    entries = [
        f"/{entry.name}/" if entry.is_dir() else f"/{entry.name}"
        for entry in static_dir.iterdir()
        if not entry.name.startswith(".")
    ]
    uncovered = sorted(entry for entry in entries if not _covered(entry))
    assert not uncovered, (
        f"frontend/static/ has {uncovered}, which neither @static_files nor "
        "@fonts covers; served unstamped, it would sit in Bunny for 30 days "
        "with no purge path. Extend @static_files or move it under /images/"
    )


def test_every_asset_reference_in_app_html_has_a_policy() -> None:
    app_html = (_ROOT / "frontend" / "src" / "app.html").read_text()
    references = re.findall(r"%sveltekit\.assets%(/[^\"'\s]+)", app_html)
    assert references, (
        "app.html should reference at least one asset via %sveltekit.assets%"
    )
    uncovered = [ref for ref in references if not _covered(ref)]
    assert not uncovered, (
        f"app.html references {uncovered} but no Caddy cache policy covers them"
    )


def test_static_files_policy_bounds_staleness_to_a_day_at_the_edge() -> None:
    match = re.search(
        r'^header @static_files >Cache-Control "([^"]+)"\s*$',
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must set a deferred Cache-Control on @static_files"
    directives = {d.strip() for d in match.group(1).split(",")}
    assert "public" in directives, (
        f"static files must be shareable, got {match.group(1)!r}"
    )
    assert "s-maxage=86400" in directives, (
        "unfingerprinted static files are replaced in place, so the edge copy "
        f"must expire within a day, got {match.group(1)!r}"
    )
    assert "immutable" not in directives, (
        "unfingerprinted files must never be immutable: a replaced favicon "
        "would never reach a browser that holds the old one"
    )


def test_env_js_has_a_short_edge_policy() -> None:
    assert _path_patterns("@env") == ["/_app/env.js"], (
        "@env must match exactly /_app/env.js, the one /_app/ file SvelteKit "
        "answers without Cache-Control"
    )
    match = re.search(
        r'^header @env >Cache-Control "([^"]+)"\s*$', _caddyfile(), re.MULTILINE
    )
    assert match, "Caddyfile must set a deferred Cache-Control on @env"
    directives = {d.strip() for d in match.group(1).split(",")}
    assert "max-age=0" in directives, (
        "/_app/env.js carries the Sentry release tag, so browsers must "
        f"revalidate it on every load, got {match.group(1)!r}"
    )
    assert "s-maxage=60" in directives, (
        f"the edge must not hold /_app/env.js past a deploy, got {match.group(1)!r}"
    )


def test_every_matcher_bound_cache_control_is_deferred() -> None:
    caddyfile = _caddyfile()
    plain = re.findall(r'^header (@\w+) Cache-Control "', caddyfile, re.MULTILINE)
    assert not plain, (
        f"{plain} set Cache-Control in the plain form; a deferred policy lower in "
        "the file replaces it on any path that policy matches, so a 403 or a "
        "redirect on a font URL would leave with a one-year TTL"
    )
    in_blocks = [
        matcher
        for matcher, body in re.findall(
            r"^header (@\w+) \{\n(.*?)^\}", caddyfile, re.MULTILINE | re.DOTALL
        )
        if re.search(r"^\s*Cache-Control\s", body, re.MULTILINE)
    ]
    assert not in_blocks, (
        f"{in_blocks} set Cache-Control inside a header block, which is the plain "
        "form; move it to its own `>Cache-Control` line"
    )


def test_caddy_written_errors_are_stamped() -> None:
    """A 502 from a failed dial is written outside the deferred wrappers."""
    match = re.search(
        r"^handle_errors \{\n(.*?)^\}", _caddyfile(), re.MULTILINE | re.DOTALL
    )
    assert match, (
        "Caddyfile must define handle_errors: the 502 Caddy writes when Node or "
        "Gunicorn is down reaches neither the ?Cache-Control default nor any "
        "deferred policy, and would inherit Bunny's 30-day default"
    )
    body = match.group(1)
    assert re.search(r'^\s*header >Cache-Control "no-store"\s*$', body, re.MULTILINE), (
        "handle_errors must stamp no-store in the deferred form"
    )
    assert re.search(r"^\s*respond .*\{err\.status_code\}\s*$", body, re.MULTILINE), (
        "handle_errors must answer with the original error status, or a 502 "
        "would be rewritten to 200 and uptime monitoring would read it as up"
    )


def test_proxied_policies_use_the_deferred_form() -> None:
    caddyfile = _caddyfile()
    for matcher in PROXIED_MATCHERS:
        assert re.search(
            rf'^header {matcher} >Cache-Control "[^"]+"\s*$', caddyfile, re.MULTILINE
        ), f"{matcher} must set Cache-Control with the deferred `>` form"
        assert not re.search(
            rf'^header {matcher} Cache-Control "', caddyfile, re.MULTILINE
        ), (
            f"{matcher} sets Cache-Control in the plain form; the proxy would add "
            "the upstream value beside it"
        )
        block = re.search(
            rf"^header {matcher} \{{\n(.*?)^\}}", caddyfile, re.MULTILINE | re.DOTALL
        )
        in_block = block is not None and re.search(
            r"^\s*Cache-Control\s", block.group(1), re.MULTILINE
        )
        assert not in_block, (
            f"{matcher} sets Cache-Control inside a header block, which is the "
            "plain form; move it to its own `>Cache-Control` line"
        )
