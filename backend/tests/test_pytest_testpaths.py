"""``testpaths`` is an allowlist, and an allowlist drops what it forgets silently."""

from __future__ import annotations

import pytest

SKIPPED_DIRS = frozenset({".venv", "node_modules", "__pycache__", "edge_tests"})


def test_every_test_file_is_under_a_testpath(pytestconfig: pytest.Config) -> None:
    root = pytestconfig.rootpath
    testpaths = [root / p for p in pytestconfig.getini("testpaths")]

    uncollected = sorted(
        str(path.relative_to(root))
        for path in root.rglob("test_*.py")
        if not SKIPPED_DIRS.intersection(path.relative_to(root).parts)
        and not any(path.is_relative_to(tp) for tp in testpaths)
    )
    assert not uncollected, (
        f"test files outside testpaths, so a bare `pytest` never runs them: "
        f"{uncollected}. Add their directory to testpaths in pytest.ini."
    )
