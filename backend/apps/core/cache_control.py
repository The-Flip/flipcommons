"""``Cache-Control`` for the public API, the one Django surface a shared cache
may store.

The directive follows the request's content audience, the same dimension the
origin response cache keys on: kiosk responses carry show-all content and must
never be stored by a shared cache. ``max-age=0`` keeps a consumer's own cache
revalidating on every use, which the edge answers with a ``304`` from its held
copy.

Each URL is its own edge entry on its own clock, so two responses fetched
within the window can reflect the catalog at different moments. The API
description publishes the window so consumers can plan around it.
"""

from __future__ import annotations

from django.http import HttpResponse

from apps.core.licensing import current_audience

# A cost ceiling, not a freshness promise: the API is free and near-
# asynchronous, and however often anyone syncs, the origin builds each dump
# at most once per window per PoP. Lengthening it later costs nothing;
# shortening it needs a purge, because a PoP keeps serving under the TTL it
# cached with. A query string on an export URL fetches the live catalog.
PUBLIC_API_EDGE_TTL = 24 * 60 * 60  # seconds

_SHARED = f"public, max-age=0, s-maxage={PUBLIC_API_EDGE_TTL}"
_NEVER_STORED = "private, no-store"


def public_api_cache_control() -> str:
    """The directive for a successful response to the current request."""
    return _NEVER_STORED if current_audience() == "kiosk" else _SHARED


def stamp_public_api_cache_control(response: HttpResponse) -> HttpResponse:
    """Stamp *response* and return it."""
    response["Cache-Control"] = public_api_cache_control()
    return response


def public_api_freshness_summary() -> str:
    """The edge window in words, for the published API description."""
    return humanize_seconds(PUBLIC_API_EDGE_TTL)


def humanize_seconds(seconds: int) -> str:
    """Whole hours or whole minutes: "24 hours", "1 hour", "5 minutes"."""
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    minutes = seconds // 60
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
