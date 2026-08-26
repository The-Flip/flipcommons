"""SvelteKit SSR must reach the API through Caddy, never Gunicorn directly.

Gunicorn's sync worker force-closes the connection after every response.
A direct Node -> Gunicorn ``fetch`` therefore gets a FIN the instant the
body ends, and on a response large enough to pause undici's HTTP/1 parser
under backpressure, Node 24 asserts ``!this.paused`` from a socket
``'end'`` handler — uncatchable, killing the SSR process and, with it, the
container. Routing through Caddy gives Node a keep-alive upstream, so the
branch that asserts is never reached. See
https://github.com/The-Flip/flipcommons/issues/726.

Nothing at runtime notices if this comes undone: the direct-to-Gunicorn
URL works fine until a big enough response meets a slow enough consumer.
These assertions pin the routing, across all three files the contract
spans. They do not exercise the property that makes the routing work —
that Caddy hands Node a keep-alive connection — which would need a
running Caddy. A directive that disabled keep-alive would leave every
test in here green.
"""

from __future__ import annotations

import re

from django.conf import settings

_ROOT = settings.BASE_DIR.parent


def _start_production() -> str:
    return (_ROOT / "scripts" / "start-production").read_text()


def _dockerfile() -> str:
    return (_ROOT / "Dockerfile").read_text()


def _caddyfile() -> str:
    return (_ROOT / "Caddyfile").read_text()


def test_entrypoint_points_ssr_at_the_caddy_listener() -> None:
    assert re.search(
        r'^export INTERNAL_API_BASE_URL="http://127\.0\.0\.1:\$\{PORT\}"\s*$',
        _start_production(),
        re.MULTILINE,
    ), (
        "scripts/start-production must export INTERNAL_API_BASE_URL pointing at "
        "Caddy's PORT listener, not at Gunicorn"
    )


def test_entrypoint_does_not_point_ssr_at_gunicorn() -> None:
    assert not re.search(
        r"INTERNAL_API_BASE_URL=.*DJANGO_PORT",
        _start_production(),
    ), "INTERNAL_API_BASE_URL must not resolve to the Gunicorn port"


def test_image_does_not_bake_an_internal_api_base_url() -> None:
    """Railway injects PORT at runtime, so the image cannot hold the value.

    An ``ENV`` line here would also be a second source of truth that the
    entrypoint's export happens to shadow — leaving a wrong port one deleted
    line away from taking effect.
    """
    assert not re.search(
        r"^\s*(ENV|ARG)\b[^\n]*\bINTERNAL_API_BASE_URL",
        _dockerfile(),
        re.MULTILINE,
    ), (
        "Dockerfile must not set INTERNAL_API_BASE_URL; scripts/start-production "
        "owns it because the value depends on the runtime-injected PORT"
    )


def test_caddy_listens_on_the_port_ssr_calls() -> None:
    assert re.search(r"^:\{\$PORT:8080\}\s*$", _caddyfile(), re.MULTILINE), (
        "Caddy must listen on $PORT — scripts/start-production builds "
        "INTERNAL_API_BASE_URL from it"
    )


def test_caddy_routes_the_api_prefix_to_django() -> None:
    match = re.search(r"^@django\s+path\s+(.+)$", _caddyfile(), re.MULTILINE)
    assert match, "Caddyfile must define a @django path matcher"
    paths = match.group(1).split()
    # SSR's API calls enter through this matcher, so both the bare prefix and
    # the subtree have to stay in it.
    assert "/api" in paths, f"@django must match /api, got {paths!r}"
    assert "/api/*" in paths, f"@django must match /api/*, got {paths!r}"


def test_caddy_proxies_the_api_prefix_to_the_gunicorn_port() -> None:
    match = re.search(
        r"^handle @django \{\n\s*reverse_proxy\s+(\S+)",
        _caddyfile(),
        re.MULTILINE,
    )
    assert match, "the @django handle must reverse_proxy to Gunicorn"
    assert match.group(1) == "127.0.0.1:{$DJANGO_PORT:8000}", (
        f"unexpected @django upstream {match.group(1)!r}"
    )
