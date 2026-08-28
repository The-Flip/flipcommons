"""``pull/sentry`` never loses an issue to a narrower window.

An issue row is mutable state -- its status, its all-time count, its
``lastSeen`` -- so unlike an event it has no timestamp axis to append along.
Replacing the file wholesale made ``--days`` destructive in one direction:
pulling the last day to get today's events discarded every issue that had no
activity today, because the issue list is also the iteration source for the
event fetch and one window scopes both. Merging on the issue id fixes that,
but only once a row records *when* it was observed -- otherwise the merged
file interleaves readings from different instants with nothing to tell them
apart, which is a worse failure than the one it replaces.
"""

from __future__ import annotations

import json
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

from django.conf import settings


def _load_sentry() -> ModuleType:
    """Import ``production_logs/pull/sentry``, which has no ``.py`` suffix."""
    path = settings.BASE_DIR.parent / "production_logs" / "pull" / "sentry"
    loader = SourceFileLoader("sentry_pull", str(path))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


sentry = _load_sentry()

WIDE = "2026-08-01T00:00:00+00:00"
NARROW = "2026-08-28T00:00:00+00:00"


def _issue(id: str, count: str, last_seen: str) -> dict[str, str]:
    return {"id": id, "shortId": f"FC-{id}", "count": count, "lastSeen": last_seen}


def _read(path: Path) -> list[dict[str, str]]:
    return list(json.loads(path.read_text()))


def test_narrow_pull_keeps_issues_the_window_did_not_ask_for(tmp_path: Path) -> None:
    """The whole point: a 1-day pull must not discard a 30-day pull's reach."""
    path = tmp_path / "issues.json"
    month = [
        _issue("1", "4", "2026-08-02T00:00:00Z"),
        _issue("2", "9", "2026-08-27T00:00:00Z"),
    ]
    sentry.merge_snapshot(path, month, key="id", observed_at=WIDE)

    today = [_issue("2", "11", "2026-08-28T00:00:00Z")]
    sentry.merge_snapshot(path, today, key="id", observed_at=NARROW)

    assert [row["id"] for row in _read(path)] == ["1", "2"]


def test_refetched_issue_supersedes_the_stored_one(tmp_path: Path) -> None:
    """A row seen again is state as of now, not as of the earlier pull."""
    path = tmp_path / "issues.json"
    sentry.merge_snapshot(
        path, [_issue("2", "9", "2026-08-27T00:00:00Z")], key="id", observed_at=WIDE
    )
    sentry.merge_snapshot(
        path, [_issue("2", "11", "2026-08-28T00:00:00Z")], key="id", observed_at=NARROW
    )

    (row,) = _read(path)
    assert row["count"] == "11"
    assert row["_observed_at"] == NARROW


def test_every_row_records_when_it_was_observed(tmp_path: Path) -> None:
    """Without the stamp, merging interleaves vintages with nothing to separate them."""
    path = tmp_path / "issues.json"
    sentry.merge_snapshot(
        path, [_issue("1", "4", "2026-08-02T00:00:00Z")], key="id", observed_at=WIDE
    )
    sentry.merge_snapshot(
        path, [_issue("2", "9", "2026-08-28T00:00:00Z")], key="id", observed_at=NARROW
    )

    assert {row["id"]: row["_observed_at"] for row in _read(path)} == {
        "1": WIDE,
        "2": NARROW,
    }


def test_merging_into_nothing_is_just_the_fresh_rows(tmp_path: Path) -> None:
    path = tmp_path / "issues.json"
    sentry.merge_snapshot(
        path, [_issue("1", "4", "2026-08-02T00:00:00Z")], key="id", observed_at=WIDE
    )

    assert [row["id"] for row in _read(path)] == ["1"]
