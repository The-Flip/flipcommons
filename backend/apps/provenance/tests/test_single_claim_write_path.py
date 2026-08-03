"""Guard: the single ``Claim`` / ``ChangeSet`` persistence chokepoints.

import-linter (``pyproject.toml``) enforces that only the interactive write
surfaces may *import* the writer modules — but it sees imports, not call sites,
and these models are imported everywhere for reads, so an import contract cannot
tell a read from a write. This AST guard holds the *persistence* line in two
tiers, applied to both ``Claim`` and ``ChangeSet``:

* **Tier 1 — mint methods**: ``X.objects.{create,bulk_create,get_or_create,
  update_or_create}`` only in the writer module (``claim_writer`` /
  ``changeset_writer``) and the ingest bulk path (``claim_ingest/apply/persist.py``).
* **Tier 2 — construction**: a bare ``X(...)`` call only in the ingest planning /
  bulk modules that legitimately build unsaved instances. AST can't attribute an
  ``instance.save()`` to a model without type inference, so *construction* is the
  detectable proxy — you can't ``.save()`` what you don't construct. This closes
  the bare-construction hole the mint-method tier alone would leave open.

The writer modules mint via ``.objects.create`` (Tier 1), not bare construction,
so they appear in the Tier-1 allowlist only; ``persist.py`` constructs *and*
bulk-creates ``ChangeSet``, so it appears in both ChangeSet tiers.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from apps.core.tests._source_guard import production_sources

# Persisting manager methods. Reads (filter/get/...) are not mints.
_MINT_METHODS = frozenset(
    {"create", "bulk_create", "get_or_create", "update_or_create"}
)

_APPS_DIR = Path(__file__).resolve().parents[2]  # .../backend/apps


def _mint_method_calls(tree: ast.AST, model: str) -> list[str]:
    """Method names of every ``<model>.objects.<mint>(...)`` call in ``tree``."""
    hits: list[str] = []
    for node in ast.walk(tree):
        func = node.func if isinstance(node, ast.Call) else None
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _MINT_METHODS
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "objects"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == model
        ):
            hits.append(func.attr)
    return hits


def _construction_calls(tree: ast.AST, model: str) -> list[str]:
    """Every bare ``<model>(...)`` Name-call in ``tree`` (instance construction)."""
    hits: list[str] = []
    for node in ast.walk(tree):
        func = node.func if isinstance(node, ast.Call) else None
        if isinstance(func, ast.Name) and func.id == model:
            hits.append(model)
    return hits


class GuardSpec(NamedTuple):
    """One (model, tier) persistence rule: a detector + its sanctioned files."""

    label: str
    model: str
    detector: Callable[[ast.AST, str], list[str]]
    sanctioned: frozenset[str]  # paths relative to ``apps/``


_SPECS = [
    GuardSpec(
        "Claim mint methods",
        "Claim",
        _mint_method_calls,
        frozenset({"provenance/claim_writer.py", "claim_ingest/apply/persist.py"}),
    ),
    GuardSpec(
        "ChangeSet mint methods",
        "ChangeSet",
        _mint_method_calls,
        frozenset({"provenance/changeset_writer.py", "claim_ingest/apply/persist.py"}),
    ),
    GuardSpec(
        "Claim construction",
        "Claim",
        _construction_calls,
        frozenset({"claim_ingest/apply/claims.py"}),
    ),
    GuardSpec(
        "ChangeSet construction",
        "ChangeSet",
        _construction_calls,
        frozenset({"claim_ingest/apply/persist.py"}),
    ),
]


@pytest.mark.parametrize("spec", _SPECS, ids=lambda s: s.label)
def test_no_unsanctioned_persistence(spec: GuardSpec) -> None:
    offenders = [
        rel
        for path in production_sources()
        if (rel := path.relative_to(_APPS_DIR).as_posix()) not in spec.sanctioned
        and spec.detector(ast.parse(path.read_text()), spec.model)
    ]
    assert not offenders, (
        f"{spec.model} rows must be persisted only through the sanctioned "
        f"modules ({', '.join(sorted(spec.sanctioned))}). "
        f"Unsanctioned {spec.label.lower()} in: " + ", ".join(sorted(offenders))
    )


@pytest.mark.parametrize("spec", _SPECS, ids=lambda s: s.label)
def test_sanctioned_paths_not_vacuous(spec: GuardSpec) -> None:
    """Canary: each tier's allowlisted files actually exhibit the pattern."""
    for rel in sorted(spec.sanctioned):
        tree = ast.parse((_APPS_DIR / rel).read_text())
        assert spec.detector(tree, spec.model), (
            f"{rel} no longer matches '{spec.label}' — the guard would pass "
            "vacuously; update the allowlist."
        )
