"""Cloudflare R2 manifest-download helper for the data-patch pull command.

Used by the ``pull_patches`` management command.
Pulls are manifest-driven: a ``manifest.json`` lists ``{path, size, sha256}``
entries; this downloads the files a caller wants and verifies each checksum.

Uses only stdlib (``urllib.request``) so it works on Railway's slim Python image.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import tempfile
import urllib.request
from collections.abc import Callable, Collection
from typing import Any, NamedTuple, cast
from urllib.error import HTTPError

from apps.core.user_agent import USER_AGENT

# Default local download directory, shared by the pull commands.
DEFAULT_DEST = os.path.join(tempfile.gettempdir(), "ingest_sources")

# Force IPv4 for all socket lookups in this process. stdlib's urllib has no
# Happy Eyeballs (RFC 8305): when DNS returns both v4 and v6 records and the
# v6 path is unreachable, urlopen blocks for the full ~30s kernel TCP timeout
# per request before falling back to v4. Cloudflare R2's v6 anycast prefix is
# intermittently unreachable from consumer networks; v4 always works. Filtering
# getaddrinfo to AF_INET takes the working path immediately. Applied at import
# so every command that imports this helper benefits.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(
    host: Any,  # noqa: ANN401 - matches socket.getaddrinfo's overloaded signature
    port: Any,  # noqa: ANN401
    family: int = 0,
    *args: Any,  # noqa: ANN401
    **kwargs: Any,  # noqa: ANN401
) -> Any:  # noqa: ANN401
    return _orig_getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)


socket.getaddrinfo = _ipv4_only_getaddrinfo

# Hard ceiling on every HTTP read. Without this, urlopen blocks indefinitely
# on a stalled connection — the symptom that motivated the IPv4 forcing above.
# 30s is long enough for the largest current manifest entry over a slow link
# but short enough to surface real network failures as errors, not hangs.
_TIMEOUT_SECONDS = 30

_OPENER = urllib.request.build_opener()
_OPENER.addheaders = [("User-Agent", USER_AGENT)]


class PullCounts(NamedTuple):
    """Per-manifest tally rolled up by the calling command for its summary."""

    downloaded: int
    up_to_date: int
    ignored: int


def _urlopen(url: str) -> http.client.HTTPResponse:
    # OpenerDirector.open() is typed as Any in typeshed; the concrete return for
    # http/https URLs is an HTTPResponse.
    return cast(http.client.HTTPResponse, _OPENER.open(url, timeout=_TIMEOUT_SECONDS))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def download_manifest(
    *,
    base_url: str,
    manifest_path: str,
    local_prefix: str,
    dest: str,
    needed_files: Collection[str] | None = None,
    required: bool = False,
    log: Callable[[str], None],
    warn: Callable[[str], None],
) -> PullCounts:
    """Fetch one R2 manifest and download the files it lists into ``dest``.

    ``base_url`` is the bucket root; ``manifest_path`` is the manifest's key
    relative to it (e.g. ``"flippatch/manifest.json"``). Files are stored under
    ``dest/local_prefix + entry["path"]``. When ``needed_files`` is given, only
    entries whose path is in it are downloaded (the rest are tallied as
    ``ignored``); when ``None``, every entry is downloaded.

    A missing manifest (HTTP error) is, by default, reported via ``warn`` and
    yields all-zero counts rather than raising, so one optional source among
    several doesn't break the whole pull. Pass ``required=True`` when this is the
    sole source of its data — the ``HTTPError`` then propagates so the caller can
    fail loudly instead of silently reporting "0 downloaded".
    """
    manifest_url = f"{base_url}/{manifest_path}"
    log(f"Fetching {manifest_url}")
    try:
        with _urlopen(manifest_url) as resp:
            manifest = json.loads(resp.read())
    except HTTPError as e:
        if required:
            raise
        warn(f"  Skipped ({e.code})")
        return PullCounts(0, 0, 0)

    # Files in a manifest are listed relative to that manifest's directory.
    manifest_base = base_url
    if "/" in manifest_path:
        manifest_base = f"{base_url}/{manifest_path.rsplit('/', 1)[0]}"

    downloaded = up_to_date = ignored = 0
    for entry in manifest:
        rel_path = entry["path"]

        if needed_files is not None and rel_path not in needed_files:
            ignored += 1
            continue

        expected_size = entry["size"]
        expected_sha = entry["sha256"]
        local_path = os.path.join(dest, local_prefix + rel_path)

        # Skip if local file already matches size and checksum.
        if (
            os.path.exists(local_path)
            and os.path.getsize(local_path) == expected_size
            and sha256(local_path) == expected_sha
        ):
            up_to_date += 1
            continue

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        file_url = f"{manifest_base}/{rel_path}"
        log(f"  {local_prefix}{rel_path}")
        with _urlopen(file_url) as resp, open(local_path, "wb") as f:
            f.write(resp.read())

        actual_sha = sha256(local_path)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Checksum mismatch for {rel_path}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        downloaded += 1

    return PullCounts(downloaded, up_to_date, ignored)
