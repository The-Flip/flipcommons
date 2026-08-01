"""Guard for the lineage-FK-claims → edge-claims migration (catalog 0021).

``0021`` rewrites ``converted_from`` / ``bootleg_of`` / ``licensed_build_of``
claims in place into ``model_relationship`` edge claims and materializes the
edge rows; ``0022`` re-runs the same transform as a final sweep and then drops
the legacy columns.

The transform's behavior matrix (value mapping, in-place rewrite, the
same-actor collision rule, inactive/dangling/cleared handling) was covered by
live-schema tests while the legacy columns existed — see this file's history
before catalog 0022. Those tests drove ``transform_lineage_claims`` against
the live model registry, which no longer carries the columns, so they cannot
run post-drop; the transform itself is frozen migration history. What remains
verified here is the one live coupling — the inlined claim_key format must
match the live builder's canonical output, because post-deploy supersedes and
removals match migration-written claims by key. End-to-end verification of
the 0021+0022 deploy path is the rebuild loop: restore ``db.pre-0039.sqlite3``, migrate,
replay the patches and assert convergence.
"""

from __future__ import annotations

import importlib

from apps.provenance.claims import build_relationship_claim

_migration = importlib.import_module(
    "apps.catalog.migrations.0021_lineage_fk_claims_to_edges"
)


def test_claim_key_format_locked_to_live_builder():
    """The inlined key format must match make_claim_key's canonical output."""
    live_key, _value = build_relationship_claim(
        "model_relationship",
        {
            "target_machine": 42,
            "target_label": "",
            "relationship_type": "conversion",
            "license_status": "unknown",
        },
    )
    assert _migration._edge_claim_key(42) == live_key
