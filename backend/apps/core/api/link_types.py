"""Wikilink picker / autocomplete endpoints."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from apps.core.autocomplete import get_autocomplete_type, run_autocomplete
from apps.core.schemas import (
    LinkTargetListSchema,
    LinkTargetSchema,
    LinkTypeSchema,
)
from apps.core.wikilinks import get_picker_type, get_picker_types

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

link_types_router = Router()


@link_types_router.get("/", response=list[LinkTypeSchema])
def list_link_types(request: HttpRequest) -> list[dict[str, str]]:
    """Return all link types offered in the wikilink picker."""
    return get_picker_types()


@link_types_router.get("/targets/", response=LinkTargetListSchema)
def search_link_targets(
    request: HttpRequest,
    type: str,
    q: str = "",
) -> LinkTargetListSchema:
    """Search within a picker type for autocomplete results.

    Standard-flow types only — custom-flow picker types (citations) drive
    their own frontend flow and never hit this endpoint. Delegates to the
    shared autocomplete engine registered under the same ``name``, mapping each
    ``{value, label}`` row onto the wikilink token shape ``{ref, label}`` the
    ``[[`` frontend expects (so the picker gains the engine's abbreviation /
    alias matching and diacritic folding for free, backend-only).
    """
    pt = get_picker_type(type)
    if (
        pt is None
        or not pt.is_enabled()
        or pt.flow != "standard"
        or get_autocomplete_type(type) is None
    ):
        raise HttpError(400, f"Invalid or unsupported link type: {type!r}")

    rows = run_autocomplete(type, q)
    results = [LinkTargetSchema(ref=row.value, label=row.label) for row in rows]
    return LinkTargetListSchema(results=results)
