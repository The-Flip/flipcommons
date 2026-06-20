"""Tests for catalog name normalization.

The case table is loaded from ``docs/fixtures/normalize_catalog_name_cases.json``,
which is shared with ``frontend/src/lib/naming.test.ts`` so both implementations
run against the same inputs and the two implementations can't drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.catalog.engine.naming import normalize_catalog_name

_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "fixtures"
    / "normalize_catalog_name_cases.json"
)

with _FIXTURE.open() as f:
    _CASES: list[tuple[str, str]] = [tuple(c) for c in json.load(f)["cases"]]


@pytest.mark.parametrize(("raw", "expected"), _CASES)
def test_normalize_catalog_name(raw: str, expected: str) -> None:
    assert normalize_catalog_name(raw) == expected
