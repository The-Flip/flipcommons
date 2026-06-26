"""Claim resolution logic.

Resolution materializes the catalog (denormalized columns + through-tables)
from claims: for each catalog entity, fetch its active claims, pick the winner
per claim_key (highest source priority, most recent if tied), and write the
resolved value into the read model.

Each dimension has its own merge policy, in CRDT register/set terms: scalar, FK
and ``status`` are **last-writer-wins registers** (one winner per claim_key);
relationship membership is a **set** with **per-element last-writer-wins** (each
member independently winner-picked, an ``exists=false`` tombstone able to win and
remove it) — *not* add-wins, so never union members instead of ranking them. The
materialized columns are a view over the claim log; anything that needs a
resolved value reuses these primitives (``ranked_claims``, ``member_is_present``,
``is_live``) and matches this path — never reimplements the merge, since a second
implementation is where a derived value drifts from what apply produces.

Every catalog entity — MachineModel included — resolves through the same generic
per-entity (:func:`resolve_entity`) and bulk (:func:`resolve_all_entities`) paths,
dispatched by entity type and changed claim field names in :mod:`._dispatch`.
"""

from __future__ import annotations

from ._dispatch import register_catalog_resolve_handlers
from ._entities import (
    _resolve_bulk,
    _resolve_single,
    resolve_all_entities,
    resolve_entity,
)
from ._media import resolve_media_attachments
from ._relationships import (
    resolve_all_corporate_entity_locations,
    resolve_all_credits,
    resolve_all_model_abbreviations,
    resolve_all_series_credits,
    resolve_all_themes,
    resolve_all_title_abbreviations,
)

__all__ = [
    "_resolve_bulk",
    "_resolve_single",
    "register_catalog_resolve_handlers",
    "resolve_all_corporate_entity_locations",
    "resolve_all_credits",
    "resolve_all_entities",
    "resolve_all_model_abbreviations",
    "resolve_all_series_credits",
    "resolve_all_themes",
    "resolve_all_title_abbreviations",
    "resolve_entity",
    "resolve_media_attachments",
]
