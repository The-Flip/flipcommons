"""Absolute URLs and the same-site host allowlist, derived from ``SITE_ORIGIN``."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from django.conf import settings


def site_host() -> str:
    """Host of ``SITE_ORIGIN``, port included.

    ``url_has_allowed_host_and_scheme`` compares against ``netloc``;
    ``hostname`` would drop the port and reject every development URL.
    """
    return urlsplit(settings.SITE_ORIGIN).netloc


def absolute_site_url(path: str) -> str:
    """Resolve ``path`` against ``SITE_ORIGIN``, passing absolute URLs through.

    ``urljoin`` reads a scheme-relative ``//host/x`` as absolute, so callers
    must pass configured settings rather than request data.
    """
    if path.startswith(("http://", "https://")):
        return path
    return urljoin(settings.SITE_ORIGIN, path)
