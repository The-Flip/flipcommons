"""Guard: the single ``Claim`` persistence chokepoint.

import-linter (``pyproject.toml``) enforces that only the interactive write
surfaces may *import* the mint primitive — but it sees imports, not call sites,
and ``Claim`` is imported everywhere for reads, so an import contract cannot tell
a read from a write. This AST guard holds the *persistence* line: no production
module may call ``Claim.objects.{create,bulk_create,get_or_create,update_or_create}``
except the two sanctioned mint sites — ``claim_writer`` (the interactive
primitive ``_assert_claim``) and the ingest bulk path. Bare ``Claim(...)``
construction is fine: ingest builds unsaved instances that persist only through
the sanctioned ``bulk_create``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from apps.core.tests._source_guard import production_sources

# Persisting manager methods. Reads (filter/get/...) and bare ``Claim(...)``
# construction are not mints and are left alone.
_MINT_METHODS = frozenset(
    {"create", "bulk_create", "get_or_create", "update_or_create"}
)

# The only two modules allowed to persist Claim rows, relative to ``apps/``.
_SANCTIONED = frozenset(
    {
        "provenance/claim_writer.py",
        "claim_ingest/apply/persist.py",
    }
)

_APPS_DIR = Path(__file__).resolve().parents[2]  # .../backend/apps


def _claim_mint_methods(tree: ast.AST) -> list[str]:
    """Method names of every ``Claim.objects.<mint>(...)`` call in ``tree``."""
    hits: list[str] = []
    for node in ast.walk(tree):
        func = node.func if isinstance(node, ast.Call) else None
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _MINT_METHODS
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "objects"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "Claim"
        ):
            hits.append(func.attr)
    return hits


def test_no_unsanctioned_claim_persistence() -> None:
    offenders = [
        rel
        for path in production_sources()
        if (rel := path.relative_to(_APPS_DIR).as_posix()) not in _SANCTIONED
        and _claim_mint_methods(ast.parse(path.read_text()))
    ]
    assert not offenders, (
        "Claim rows must be minted only through claim_writer._assert_claim or the "
        "sanctioned ingest bulk path. Unsanctioned Claim.objects mint call(s) in: "
        + ", ".join(sorted(offenders))
    )


def test_sanctioned_paths_actually_mint() -> None:
    """Canary: the guard isn't passing vacuously — both sanctioned files mint."""
    for rel in sorted(_SANCTIONED):
        tree = ast.parse((_APPS_DIR / rel).read_text())
        assert _claim_mint_methods(tree), (
            f"{rel} no longer mints a Claim — the guard would pass vacuously"
        )
