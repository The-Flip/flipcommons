"""Grep gate: ``actor`` is the only attribution path in production code.

"Drop dead stuff" removed ``Claim.user`` / ``Claim.source`` / ``ChangeSet.user``.
The real enforcement is the schema + mypy (any field access is now a hard error);
this coarse substring gate is the backstop that stops a new module from
re-introducing a legacy-attribution read. See ``apps.core.tests._source_guard``
and ``test_ranking_is_canonical`` for the pattern.

The allow-list is the handful of provenance modules that name the old columns in
prose/docstrings only (explaining the historical behavior they replaced) — never
as a live read. A real read would fail mypy first, so allow-listing prose here
doesn't weaken the guarantee.
"""

from __future__ import annotations

import pytest

from apps.core.tests._source_guard import offenders

# Paths (relative to ``apps/``) that contain a legacy spelling only in prose.
# Keep this minimal — every entry is a hole in the gate. A real read would fail
# mypy first, so allow-listing genuine prose doesn't weaken the guarantee.
_PROSE_ONLY = {
    "provenance/attribution.py",  # docstrings: "the old claim.source is None case"
    "provenance/licensing.py",  # docstring: "the old claim.source is None behavior"
}


@pytest.mark.parametrize(
    "needle",
    ["claim.user", "claim.source", "changeset.user"],
)
def test_no_legacy_attribution_reads(needle: str) -> None:
    """No production module reads a dropped attribution column.

    ``ingest_run.source`` is intentionally NOT forbidden — it is live batch
    metadata. ``actor.user`` / ``actor.source`` (the reverse accessors) don't
    match these needles.
    """
    found = offenders(needle, allow=_PROSE_ONLY)
    assert not found, (
        f"Legacy attribution read {needle!r} found outside the allow-list: "
        f"{found}. Attribution must route through `actor`."
    )
