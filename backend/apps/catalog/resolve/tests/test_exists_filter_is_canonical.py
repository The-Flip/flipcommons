"""Guard: the relationship-member exists-filter lives in exactly one place.

A member claim's ``exists`` flag (``exists=false`` is a tombstone) is read
through :func:`apps.catalog.resolve.claim_presence.member_is_present`.  This test
fails if any other module re-spells the ``value.get("exists", True)`` filter
inline instead of routing through the shared leaf — the same drift the ranking
guard (``apps/provenance/tests/test_ranking_is_canonical.py``) prevents for the
winner-pick.

Two files are allow-listed:

* ``claim_presence.py`` *defines* the leaf.
* ``provenance/validation.py`` sits *below* catalog, so it cannot import the
  catalog-located leaf; it keeps its own spelling until the leaf moves down to a
  shared layer.
"""

from __future__ import annotations

from pathlib import Path

import apps.catalog.resolve.claim_presence as presence

_CANONICAL = Path(presence.__file__).resolve()
_APPS_DIR = _CANONICAL.parents[2]  # .../backend/apps
_ALLOWLISTED = {
    _CANONICAL,
    (_APPS_DIR / "provenance" / "validation.py").resolve(),
}


def _production_sources() -> list[Path]:
    """Every non-test, non-migration app module."""
    return [
        path
        for path in _APPS_DIR.rglob("*.py")
        if "migrations" not in path.parts and "tests" not in path.parts
    ]


def test_exists_filter_routed_through_member_is_present() -> None:
    """No module re-spells the member exists-filter outside the shared leaf."""
    offenders = [
        str(path)
        for path in _production_sources()
        if path.resolve() not in _ALLOWLISTED and '.get("exists"' in path.read_text()
    ]
    assert not offenders, (
        "Inlined the member exists-filter instead of calling member_is_present: "
        f"{offenders}. Route through apps.catalog.resolve.claim_presence."
    )
