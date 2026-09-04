"""Caddy must mark the ``/__health`` liveness probe uncacheable.

Bunny's pull zone applies a 30-day default TTL to any response that
reaches it without a ``Cache-Control`` header, which would let an edge
PoP answer uptime probes from cache, reporting ``ok`` long after the
origin stopped serving. The SvelteKit hook stamps the probe too; the
Caddy line is the edge-side statement of the same policy, pinned here
against accidental deletion. The ``>`` (deferred) form is what lets
Caddy's value replace the hook's rather than stack beside it.
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
        r'^header\s+@health\s+>?Cache-Control\s+"([^"]+)"\s*$',
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "Caddyfile must set Cache-Control on the @health matcher"
    assert "no-store" in match.group(1), (
        f"the /__health probe must be uncacheable, got {match.group(1)!r}"
    )
