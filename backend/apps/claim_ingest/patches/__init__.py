"""YAML data-patch adapter: parse a patch file into an ``IngestPlan``.

A *data patch* is a small, source-attributed set of catalog claims authored
as plain YAML and applied through the existing ingest apply engine
(:mod:`apps.claim_ingest.apply`) — not a parallel engine. This package
turns a patch's text into an :class:`IngestPlan`; the ``ingest_patches``
command discovers, hashes, ledger-checks and applies them.

See ``docs/DataPatches.md`` for the file format and design rationale.

Split by pipeline layer, dependencies flowing one way (acyclic):

    _types ← parsing ← emit ← planning

- :mod:`._types` — carriers shared across layers (``_Target``, ``_CreatedKey`` …).
- :mod:`.parsing` — patch text → ``PatchDoc`` (pure, no DB).
- :mod:`.emit` — low-level verbs that build plan rows for one resolved entry.
- :mod:`.planning` — ``build_plan``: emit + cross-entry validation.

A lower layer importing a higher one is a layering smell — hoist the shared
symbol into :mod:`._types`. The package re-exports the public surface, so
callers import from ``apps.claim_ingest.patches`` regardless of layer.
"""

from __future__ import annotations

from apps.claim_ingest.patches._types import PatchError
from apps.claim_ingest.patches.parsing import (
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
from apps.claim_ingest.patches.planning import build_plan

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
