"""``pull/bunny`` never writes a haul shorter than the dump it replaces.

Bunny keeps four days and then the day is gone, so a file in
``production_logs/dumps/bunny/`` can be the only surviving copy of an
outage. Two answers destroy one. A day at the retention edge comes back
*trimmed* rather than absent -- 200, a couple of thousand rows, where the
dump holds twelve thousand -- and an empty body means aged out, logging
switched off or no traffic, three things nothing can tell apart once the
empty file has landed on top of the full one.
"""

from __future__ import annotations

import sys
from datetime import date
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest
from django.conf import settings


def _load_bunny() -> ModuleType:
    """Import ``production_logs/pull/bunny``, which has no ``.py`` suffix."""
    path = settings.BASE_DIR.parent / "production_logs" / "pull" / "bunny"
    loader = SourceFileLoader("bunny_pull", str(path))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


bunny = _load_bunny()

ZONE = bunny.Zone(
    id=5969801,
    name="flipcommons-html",
    logging_enabled=True,
    anonymization="OneDigit",
)
DARK_ZONE = ZONE._replace(logging_enabled=False)
DAY = date(2026, 8, 24)
FILENAME = "flipcommons-html.5969801.2026-08-24.log"


def _lines(count: int) -> bytes:
    """``count`` well-formed edge lines: 12 pipe fields, epoch millis third."""
    return b"".join(
        b"MISS|200|%d|118|5969801|193.186.4.0|https://www.google.com/|"
        b"https://flipcommons.org/|DEN|Mozilla/5.0|%032x|US\n"
        % (1787529600000 + n * 1000, n)
        for n in range(count)
    )


def _answer(body: bytes, status: int):
    """A stand-in for ``request`` that always answers the same way."""
    return lambda url, key: bunny.Fetched(body, status)


def test_refuses_a_haul_shorter_than_the_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retention edge trims a day rather than removing it."""
    dump = _lines(12)
    dest = tmp_path / FILENAME
    dest.write_bytes(dump)
    monkeypatch.setattr(bunny, "request", _answer(_lines(2), 200))

    with pytest.raises(bunny.ShortHaul, match="12"):
        bunny.pull_day(ZONE, DAY, "key", tmp_path)

    assert dest.read_bytes() == dump


def test_refuses_to_write_a_day_that_aged_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = _lines(3)
    dest = tmp_path / FILENAME
    dest.write_bytes(dump)
    monkeypatch.setattr(bunny, "request", _answer(b"", 404))

    with pytest.raises(bunny.ShortHaul, match="404"):
        bunny.pull_day(ZONE, DAY, "key", tmp_path)

    assert dest.read_bytes() == dump


def test_refuses_to_write_an_empty_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dump = _lines(3)
    dest = tmp_path / FILENAME
    dest.write_bytes(dump)
    monkeypatch.setattr(bunny, "request", _answer(b"", 200))

    with pytest.raises(bunny.ShortHaul):
        bunny.pull_day(ZONE, DAY, "key", tmp_path)

    assert dest.read_bytes() == dump


def test_refuses_even_when_no_dump_is_at_risk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty haul is a failed pull whether or not it would destroy one."""
    monkeypatch.setattr(bunny, "request", _answer(b"", 200))

    with pytest.raises(bunny.ShortHaul):
        bunny.pull_day(ZONE, DAY, "key", tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_names_switched_off_logging_as_the_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The zone's own setting separates 'logging off' from 'no traffic'."""
    monkeypatch.setattr(bunny, "request", _answer(b"", 200))

    with pytest.raises(bunny.ShortHaul, match="logging"):
        bunny.pull_day(DARK_ZONE, DAY, "key", tmp_path)


def test_writes_a_day_that_grew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-pulling today has to supersede this morning's partial file."""
    dest = tmp_path / FILENAME
    dest.write_bytes(_lines(2))
    grown = _lines(9)
    monkeypatch.setattr(bunny, "request", _answer(grown, 200))

    record = bunny.pull_day(ZONE, DAY, "key", tmp_path)

    assert dest.read_bytes() == grown
    assert record["rows"] == 9
    assert record["http"] == 200


def test_writes_a_day_that_held_steady(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bunny re-resolves geo between fetches, so equal-length is normal."""
    dest = tmp_path / FILENAME
    dest.write_bytes(_lines(4))
    monkeypatch.setattr(bunny, "request", _answer(_lines(4), 200))

    assert bunny.pull_day(ZONE, DAY, "key", tmp_path)["rows"] == 4


def test_a_failed_day_does_not_stop_the_perishable_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every zone-day is attempted, then the run exits non-zero.

    The oldest day is fetched first and is the one at the retention edge,
    so giving up on it would abandon today -- the only day that cannot be
    pulled again tomorrow.
    """
    attempted: list[str] = []

    def answer(url: str, key: str):
        # The first URL is the oldest day, which is the one at the edge.
        attempted.append(url)
        return bunny.Fetched(b"", 404 if len(attempted) == 1 else 200)

    monkeypatch.setattr(bunny, "read_key", lambda: "key")
    monkeypatch.setattr(bunny, "list_zones", lambda key: [ZONE])
    monkeypatch.setattr(bunny, "request", answer)
    monkeypatch.setattr(sys, "argv", ["bunny", "--days", "4", "--out", str(tmp_path)])

    with pytest.raises(SystemExit) as exit_info:
        bunny.main()

    assert exit_info.value.code not in (0, None)
    assert len(attempted) == 4
