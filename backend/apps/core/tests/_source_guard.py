"""Shared machinery for source-scanning "guard" tests.

A guard test fails the build when a forbidden text pattern appears in any
production source file outside an explicit allow-list. Substring matching is
deliberately coarse — see the module docstrings of ``test_liveness_canonical``
and ``test_ranking_is_canonical`` — it catches the one thing that matters (a
second, divergent copy of a rule, or a raw spelling of something that must route
through a canonical helper) without the weight of AST analysis.

This is the usage/spelling counterpart to import-linter: import *structure* is
enforced by the contracts in ``pyproject.toml`` (see ``docs/AppBoundaries.md``);
these guards cover patterns import-linter cannot see — a copied algorithm, a raw
attribute read. Allow-listing is by path relative to ``apps/``, not basename, so
a common filename (e.g. ``apps.py``) can be exempted in one app without
exempting every copy.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

_APPS_DIR = Path(__file__).resolve().parents[2]  # .../backend/apps


def production_sources() -> list[Path]:
    """Every non-test, non-migration app module."""
    return [
        path
        for path in _APPS_DIR.rglob("*.py")
        if "migrations" not in path.parts and "tests" not in path.parts
    ]


def offenders(needle: str, *, allow: Iterable[str] = ()) -> list[str]:
    """Production sources containing ``needle``, excluding the ``allow`` paths.

    ``allow`` entries are POSIX paths relative to ``apps/`` (e.g.
    ``"core/models/mixins.py"``). Returns the offending paths, also relative to
    ``apps/``, so the failure message is short and clickable.
    """
    allowed = set(allow)
    return [
        rel
        for path in production_sources()
        if (rel := path.relative_to(_APPS_DIR).as_posix()) not in allowed
        and needle in path.read_text()
    ]
