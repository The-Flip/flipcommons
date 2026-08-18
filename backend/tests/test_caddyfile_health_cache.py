"""Caddy must mark the ``/__health`` liveness probe uncacheable.

Bunny's pull zone applies a 30-day default TTL to any response that
reaches it without a ``Cache-Control`` header, and SvelteKit leaves
``+server.ts`` endpoints unstamped on purpose (see
``frontend/src/lib/cache-control.server.ts``). Together those defaults
let an edge PoP answer uptime probes from cache, reporting ``ok`` long
after the origin stopped serving. Only Caddy can close the gap, so this
test pins the directive against accidental deletion.
"""

from __future__ import annotations

import re

from django.conf import settings


def _caddyfile() -> str:
    return (settings.BASE_DIR.parent / "Caddyfile").read_text()


def test_caddyfile_matches_the_health_probe_path() -> None:
    assert re.search(
        r"^@health\s+path\s+/__health\s*$",
        _caddyfile(),
        re.MULTILINE,
    ), "Caddyfile must define a @health matcher for /__health"


def test_caddyfile_disables_edge_caching_on_the_health_probe() -> None:
    match = re.search(
        r'^header\s+@health\s+Cache-Control\s+"([^"]+)"\s*$',
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must set Cache-Control on the @health matcher"
    assert "no-store" in match.group(1), (
        f"the /__health probe must be uncacheable, got {match.group(1)!r}"
    )
