"""Shared plumbing for the pull scripts: credentials, day windows, HTTP, merge, manifest.

The pullers are archivers, not parsers. Rows are written to disk exactly as the
service hands them down; a row is only ever *looked at* for its timestamp (to
bucket it into a UTC-day file) and its identity key (to merge re-pulls without
duplicates). Interpretation belongs to production_logs/analyze/sql/.

Exit taxonomy, shared by every puller:

    0  success, including a day the vendor has nothing for
    1  transport failure after retries, or a verification mismatch
    2  preflight: missing credential or bad --start/--end, before any network call
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import os
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]

Row = dict[str, Any]


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def die(code: int, message: str) -> None:
    log(message)
    raise SystemExit(code)


def preflight(*names: str) -> dict[str, str]:
    """The named credentials, from the environment or the repo's .env.

    Every missing name is reported at once, before any network call, and the
    process exits 2 -- the caller never starts a pull it cannot finish.
    """
    from_env_file: dict[str, str] = {}
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            name, _, value = line.partition("=")
            from_env_file[name.strip()] = value.strip().strip("\"'")
    found: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = os.environ.get(name) or from_env_file.get(name, "")
        if value:
            found[name] = value
        else:
            missing.append(name)
    if missing:
        die(2, f"missing credential(s): {', '.join(missing)} (checked environment and {env_path})")
    return found


class Window(NamedTuple):
    """A pull window: whole UTC days, resolved to instants and to the day list."""

    start: datetime  # start day at 00:00Z
    end: datetime  # min(end day + 1 at 00:00Z, now)
    days: list[date]  # every UTC day the window touches, oldest first


def add_window_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start", required=True, metavar="YYYY-MM-DD",
        help="first UTC day to pull (inclusive, required)",
    )
    parser.add_argument(
        "--end", metavar="YYYY-MM-DD",
        help="last UTC day to pull (inclusive, default today)",
    )


def window(args: argparse.Namespace) -> Window:
    """Resolve --start/--end into a Window, exiting 2 on nonsense."""
    today = datetime.now(UTC).date()
    try:
        start_day = date.fromisoformat(args.start)
        end_day = date.fromisoformat(args.end) if args.end else today
    except ValueError as error:
        die(2, f"--start/--end must be YYYY-MM-DD UTC dates: {error}")
        raise AssertionError  # unreachable; die() always raises
    if start_day > end_day:
        die(2, f"--start {start_day} is after --end {end_day}")
    if start_day > today:
        die(2, f"--start {start_day} is in the future")
    end_day = min(end_day, today)
    start = datetime.combine(start_day, datetime.min.time(), UTC)
    end = min(
        datetime.combine(end_day + timedelta(days=1), datetime.min.time(), UTC),
        datetime.now(UTC),
    )
    days = [start_day + timedelta(days=n) for n in range((end_day - start_day).days + 1)]
    return Window(start, end, days)


class Fetched(NamedTuple):
    """One HTTP response body, with the status the caller may need to judge."""

    body: bytes
    status: int


def http_request(
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    ok_statuses: frozenset[int] = frozenset(),
    timeout: int = 180,
) -> Fetched:
    """GET (or POST, when a body is given) with retries for what is worth retrying.

    429 and transient 5xx retry with backoff, honouring Retry-After. A status in
    `ok_statuses` is returned for the caller to judge (a vendor's "nothing here"
    answer is data, not an error). Anything else exits 1 with the body excerpt.
    Asks for gzip and decodes it, since urllib will not.
    """
    for attempt in range(5):
        request = urllib.request.Request(
            url,
            data=body,
            # urllib's default agent is blocked outright by some vendor WAFs
            # (Railway's answers it with a bare 403), so always send our own.
            headers={"Accept-Encoding": "gzip", "User-Agent": "flipcommons-pull", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    payload = gzip.decompress(payload)
                return Fetched(payload, response.status)
        except urllib.error.HTTPError as error:
            payload = error.read()
            if error.headers.get("Content-Encoding") == "gzip":
                payload = gzip.decompress(payload)
            if error.code in ok_statuses:
                return Fetched(payload, error.code)
            if error.code not in (429, 500, 502, 503, 504):
                die(1, f"HTTP {error.code} on {url}\n{payload[:300].decode(errors='replace')}")
            delay = int(error.headers.get("Retry-After") or 2**attempt)
            log(f"  {error.code}; retrying in {delay}s")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            log(f"  {error}; retrying")
            time.sleep(2**attempt)
    die(1, f"gave up after repeated failures on {url}")
    raise AssertionError  # unreachable; die() always raises


class MergeResult(NamedTuple):
    """What one merge_ndjson call did to one day file."""

    rows: int  # rows now in the file
    carried: int  # rows kept from the prior file that this fetch did not return
    first_ts: str  # oldest timestamp in the merged file
    last_ts: str  # newest timestamp in the merged file


def merge_ndjson(
    path: Path,
    fresh: Iterable[Row],
    key: Callable[[Row], object],
    ts_of: Callable[[Row], str],
) -> MergeResult:
    """Merge fresh rows into the ndjson dump on disk, atomically.

    The dump is an INPUT to its own rewrite -- it can hold rows the vendor no
    longer serves -- so a re-fetched row supersedes the stored one and nothing
    is ever dropped. Written beside the file and renamed over it, because an
    interrupt partway through a truncating write would destroy the prior rows
    rather than merely failing to extend them.
    """
    prior: dict[object, Row] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                prior[key(row)] = row
    fresh_by_key = {key(row): row for row in fresh}
    merged = prior | fresh_by_key
    ordered = sorted(merged.values(), key=ts_of)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in ordered))
    tmp.replace(path)
    return MergeResult(
        rows=len(ordered),
        carried=len(prior.keys() - fresh_by_key.keys()),
        first_ts=ts_of(ordered[0]),
        last_ts=ts_of(ordered[-1]),
    )


def bucket_by_day(rows: Iterable[Row], ts_of: Callable[[Row], str]) -> dict[date, list[Row]]:
    """Rows grouped by the UTC day of their own timestamp."""
    buckets: dict[date, list[Row]] = {}
    for row in rows:
        day = datetime.fromisoformat(ts_of(row).replace("Z", "+00:00")).astimezone(UTC).date()
        buckets.setdefault(day, []).append(row)
    return buckets


def iso_z(instant: datetime) -> str:
    """ISO 8601 Z form at microsecond precision -- what the manifest stores."""
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def manifest_record(
    file: str,
    kind: str,
    rows: int,
    first_ts: str | None,
    last_ts: str | None,
    complete: bool,
    **extras: Any,
) -> Row:
    """One uniform per-file manifest entry, keyed by the file's path relative
    to the dump directory. Extras are source-specific fields."""
    return {
        "file": file,
        "kind": kind,
        "rows": rows,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "pulled_at": iso_z(datetime.now(UTC)),
        "complete": complete,
        **extras,
    }


def update_manifest(out: Path, records: list[Row]) -> None:
    """Merge this run's records into manifest.json, keyed on the file name.

    Merged rather than replaced because a run is usually scoped while the dumps
    directory accumulates across runs. A re-pulled file supersedes its record;
    records for files no longer on disk are dropped.
    """
    path = out / "manifest.json"
    merged: dict[str, Row] = {}
    if path.is_file():
        for old in json.loads(path.read_text()).get("files", []):
            merged[old["file"]] = old
    merged = {name: rec for name, rec in merged.items() if (out / name).exists()}
    for record in records:
        merged[record["file"]] = record
    files = sorted(merged.values(), key=lambda r: r["file"])
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"files": files}, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)
    growing = sum(1 for r in files if not r["complete"])
    log(f"manifest.json: {len(files)} file(s) tracked, {growing} still accumulating")
