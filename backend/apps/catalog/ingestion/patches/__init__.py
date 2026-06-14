"""YAML data-patch adapter: parse a patch file into an ``IngestPlan``.

A *data patch* is a small, source-attributed set of catalog claims authored
as plain YAML and applied through the existing ingest apply engine
(:mod:`apps.catalog.ingestion.apply`) — not a parallel engine. This package
turns a patch's text into an :class:`IngestPlan`; the ``ingest_patches``
command discovers, hashes, ledger-checks and applies them.

See ``docs/DataPatches.md`` for the file format and design rationale.

Split by pipeline layer (bottom to top):

- :mod:`._types` — carriers shared across layers (``_Target``, ``_CreatedKey`` …).
- :mod:`.parsing` — patch text → ``PatchDoc`` (pure, no DB).
- :mod:`.emit` — low-level verbs that build plan rows for one resolved entry.
- :mod:`.planning` — ``build_plan``: drives parsing output through emit, then runs
  cross-entry validation.

Dependencies flow one way — ``_types ← parsing ← emit ← planning`` (acyclic). A
lower layer importing a higher one is a layering smell: hoist the shared symbol
into :mod:`._types` instead. (A result type owned by one layer stays with its
producer — see :mod:`._types` for that split.)

This package re-exports the public surface (``load_patch``, ``build_plan``,
``parse_patch_text``, ``fingerprint``, ``PatchError``, the entry types …) so
callers import from ``apps.catalog.ingestion.patches`` regardless of which layer
a name lives in.
"""

from __future__ import annotations

from apps.catalog.ingestion.patches._types import PatchError
from apps.catalog.ingestion.patches.parsing import (
    PATCH_ID_RE,
    CreateEntry,
    DeleteEntry,
    EditEntry,
    PatchDoc,
    PatchEntry,
    fingerprint,
    load_patch,
    parse_patch_text,
)
from apps.catalog.ingestion.patches.planning import build_plan

__all__ = [
    "PATCH_ID_RE",
    "CreateEntry",
    "DeleteEntry",
    "EditEntry",
    "PatchDoc",
    "PatchEntry",
    "PatchError",
    "build_plan",
    "fingerprint",
    "load_patch",
    "parse_patch_text",
]
