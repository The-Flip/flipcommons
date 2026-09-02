"""The public origin must reach both SvelteKit runtimes from ``SITE_ORIGIN``.

adapter-node resolves ``event.url.origin`` from the ``ORIGIN`` environment
variable, falling back to the request's ``Host`` header — which is not a
reliable source for the public origin, since it varies by caller (Railway's
health check, direct hits on the Railway origin hostname) and prerendering
has no request at all. Browser code needs the same value as
``PUBLIC_SITE_ORIGIN``, since ``$env/dynamic/public`` exposes only
``PUBLIC_``-prefixed variables.

``SITE_ORIGIN`` stays the single operator-facing setting; the entrypoint
derives both names from it. These assertions pin that wiring. They do not
prove adapter-node honors ``ORIGIN`` or that anything reads
``PUBLIC_SITE_ORIGIN`` — the former is upstream behavior a script test
cannot drive, and the latter is covered by frontend vitest.
"""

from __future__ import annotations

import re

from django.conf import settings

_ROOT = settings.BASE_DIR.parent


def _start_production() -> str:
    return (_ROOT / "scripts" / "start-production").read_text()


def test_entrypoint_derives_node_origin_from_site_origin() -> None:
    assert re.search(
        r'^ORIGIN="\$\{SITE_ORIGIN\}" HOST=127\.0\.0\.1 PORT="\$\{NODE_PORT\}" '
        r"node build/index\.js &$",
        _start_production(),
        re.MULTILINE,
    ), (
        "scripts/start-production must launch Node with ORIGIN derived from "
        "SITE_ORIGIN; without it adapter-node falls back to the Host header, "
        "which varies by caller and is not the public origin"
    )


def test_entrypoint_mirrors_site_origin_into_the_public_namespace() -> None:
    assert re.search(
        r'^export PUBLIC_SITE_ORIGIN="\$\{SITE_ORIGIN:\?[^}]+\}"$',
        _start_production(),
        re.MULTILINE,
    ), (
        "scripts/start-production must export PUBLIC_SITE_ORIGIN from "
        "SITE_ORIGIN so $env/dynamic/public can pin post-hydration SEO URLs "
        "to the public origin — with the :? guard, because the Dockerfile "
        'bakes ENV SITE_ORIGIN="" and set -u does not catch set-but-empty'
    )
