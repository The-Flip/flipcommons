"""Guard: no route converts a server fault into a 5xx ``HttpError``.

Ninja answers ``HttpError`` with a status-coded response and never fires
``got_request_exception``, so a ``raise HttpError(500, ...)`` reaches neither
Sentry nor the ``django.request`` error log. A fault must propagate instead:
Django then logs the traceback and Sentry captures it, both for free. The
pattern reads like careful error handling, which is why it needs a guard.

A regex rather than :func:`offenders` so the call still matches after
ruff-format wraps the status onto its own line. ``config/`` is scanned too
because it mounts routes of its own.
"""

from __future__ import annotations

import re
from pathlib import Path

from apps.core.tests._source_guard import production_sources

_FIVE_XX_HTTP_ERROR = re.compile(r"HttpError\(\s*5\d\d\b")
_BACKEND_DIR = Path(__file__).resolve().parents[3]


def _route_sources() -> list[Path]:
    return [*production_sources(), *(_BACKEND_DIR / "config").glob("*.py")]


def test_no_route_raises_a_5xx_http_error() -> None:
    offenders = [
        path.relative_to(_BACKEND_DIR).as_posix()
        for path in _route_sources()
        if _FIVE_XX_HTTP_ERROR.search(path.read_text())
    ]
    assert offenders == []
