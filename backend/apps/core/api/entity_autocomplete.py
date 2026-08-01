"""Generic entity-autocomplete endpoint.

A thin wrapper over the shared :func:`run_autocomplete` engine: resolve the
requested ``type`` against the cross-app autocomplete registry and return its
``{value, label, sublabel}`` rows. Any app that registered an autocompletable
type from its ``AppConfig.ready()`` is reachable here under its registry key.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from apps.core.autocomplete import get_autocomplete_type, run_autocomplete
from apps.core.schemas import (
    EntityAutocompleteListSchema,
    EntityAutocompleteResultSchema,
)

entity_autocomplete_router = Router()


@entity_autocomplete_router.get("/", response=EntityAutocompleteListSchema)
def entity_autocomplete(
    request: HttpRequest,
    type: str,
    q: str = "",
) -> EntityAutocompleteListSchema:
    """Autocomplete within a registered entity type.

    ``type`` is the registry key (``manufacturer``, ``title``, …); ``q`` is the
    search term (empty → ordered top-N so a freshly-focused control isn't
    blank). Unknown types 400 rather than silently returning nothing.
    """
    if get_autocomplete_type(type) is None:
        raise HttpError(400, f"Unknown autocomplete type: {type!r}")

    rows = run_autocomplete(type, q)
    return EntityAutocompleteListSchema(
        results=[
            EntityAutocompleteResultSchema(
                value=row.value, label=row.label, sublabel=row.sublabel
            )
            for row in rows
        ]
    )
