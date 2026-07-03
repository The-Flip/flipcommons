"""The Vimeo scheme: videos on vimeo.com, keyed by numeric video id.

Two recognized shapes collapse to the numeric id: the watch page
(``vimeo.com/<id>``, optionally carrying an unlisted-access hash as a second
path segment) and the embed player on its own subdomain
(``player.vimeo.com/video/<id>``). Boundaries per shape, so a malformed URL
fails instead of collapsing to a wrong-but-valid-looking id:

- the watch shape accepts the id at the path root only, optionally followed by
  a hex unlisted hash (``vimeo.com/347119375/d0e9b81c05``) — the hash is an
  access token, not identity, so it is dropped and both forms dedup to one
  child. The hash charset is deliberately hex-only: a looser ``[a-z0-9]``
  would swallow non-video paths like ``/<id>/review``. The cost is honest —
  an unlisted video's canonical link may not be publicly viewable, but an
  unlisted video is a poor citation to begin with.
- legacy browse shapes (``/channels/<name>/<id>``, ``/groups/…``) are not
  recognized; they host-resolve to the Vimeo root and degrade to a web child.

The time axis is what makes Vimeo worth its scheme slot next to YouTube: the
start position rides in the URL **fragment** (``#t=1m30s``), not the query,
in the same unit grammar the video type already parses. ``deep_link`` builds
the fragment form; ``start_seconds_from_url`` reads it.
"""

import re
from typing import Final
from urllib.parse import parse_qs, urlparse

from apps.citation.citation_types.base import RootSeed, SourceType
from apps.citation.citation_types.video import VideoSchemeSpec, parse_start_time

# Watch-shape boundary: the id may be followed by an unlisted hex hash
# segment and/or a single trailing slash, then only query/fragment/end.
_WATCH_ID = r"(\d+)(?=(?:/[0-9a-f]{6,16})?/?(?:[?#]|$))"
# Embed-shape boundary: no hash segment on player URLs (the hash rides as a
# ``?h=`` query param there, which the boundary already tolerates).
_EMBED_ID = r"(\d+)(?=/?(?:[?#]|$))"

_URL_PATTERN = re.compile(
    r"https?://(?:"
    rf"(?:www\.)?vimeo\.com/{_WATCH_ID}"
    rf"|player\.vimeo\.com/video/{_EMBED_ID}"
    r")"
)


def _canonical_url(video_id: str) -> str:
    """The one URL every Vimeo shape collapses to."""
    return f"https://vimeo.com/{video_id}"


def _deep_link(video_id: str, start_seconds: int) -> str:
    """The watch URL that starts playback at *start_seconds*.

    Vimeo's seek syntax is a fragment, not a query param: ``#t=95s``.
    """
    return f"https://vimeo.com/{video_id}#t={start_seconds}s"


def _start_seconds_from_url(url: str) -> int | None:
    """The start-time hint in a Vimeo URL's ``#t=`` fragment.

    Vimeo writes ``#t=90s`` and ``#t=1m30s`` — the video type's unit/bare
    grammar covers both. ``t=0`` means "from the beginning" — no hint. A
    malformed value abstains rather than guessing.
    """
    try:
        fragment = urlparse(url).fragment
    except ValueError:
        return None
    for value in parse_qs(fragment).get("t", []):
        seconds = parse_start_time(value)
        if seconds:
            return seconds
    return None


VIMEO: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="vimeo",
    label="Vimeo",
    source_type=SourceType.VIDEO,
    url_pattern=_URL_PATTERN,
    id_pattern=re.compile(r"\d+"),
    canonical_url=_canonical_url,
    example_identifier="347119375",
    root_seed=RootSeed(
        name="Vimeo",
        homepage_url="https://vimeo.com/",
        # player.vimeo.com is deliberately NOT listed: it is a subdomain of
        # vimeo.com, so host-suffix recognition already resolves it.
        recognition_hosts=("vimeo.com",),
    ),
    deep_link=_deep_link,
    start_seconds_from_url=_start_seconds_from_url,
)
