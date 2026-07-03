"""The YouTube scheme: videos on youtube.com, keyed by 11-char video id.

YouTube's one video id is reachable through many URL shapes (``watch?v=``,
``youtu.be/``, ``/shorts/``, ``/embed/``, ``/live/``, mobile ``m.``) plus
trailing params — all collapse to one canonical child. The pattern is
host-bound on ``https?://<host>`` like the others so ``notyoutube.com`` can't
match, and each shape carries its own boundary so a malformed URL fails
instead of collapsing to a wrong-but-valid-looking id:

- the ``watch`` shape reads ``v=`` from the **query only** (the param scan
  can't cross ``#`` into the fragment), and the 11-char id can't continue
  into a longer token;
- the path shapes (``youtu.be/``, ``/embed/``, ``/shorts/``, ``/live/``)
  accept end/query/fragment or a single trailing slash after the id, but not
  extra path segments.

A video scheme (:class:`~apps.citation.citation_types.video.VideoSchemeSpec`):
children mint as ``video`` sources, a pasted ``?t=``/``?start=`` start time
surfaces as a structured ``SchemeMatch.start_seconds`` hint, and ``deep_link``
builds the watch URL that jumps to a cited moment.
"""

import re
from typing import Final
from urllib.parse import parse_qs, urlparse

from apps.citation.citation_types.base import RootSeed, SourceType
from apps.citation.citation_types.video import VideoSchemeSpec, parse_start_time

# Path-shape boundary: the id may be followed by a single trailing slash and
# then only a query, a fragment, or the end — never more path.
_PATH_ID = r"([A-Za-z0-9_-]{11})(?=/?(?:[?#]|$))"

_URL_PATTERN = re.compile(
    r"https?://(?:"
    r"(?:www\.|m\.)?youtube\.com/watch\?(?:[^\s#]*&)?v=([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
    rf"|(?:www\.|m\.)?youtube\.com/(?:embed|shorts|live)/{_PATH_ID}"
    rf"|(?:www\.)?youtu\.be/{_PATH_ID}"
    r")"
)


def _canonical_url(video_id: str) -> str:
    """The one URL every YouTube shape collapses to."""
    return f"https://www.youtube.com/watch?v={video_id}"


def _deep_link(video_id: str, start_seconds: int) -> str:
    """The watch URL that starts playback at *start_seconds*."""
    return f"https://www.youtube.com/watch?v={video_id}&t={start_seconds}s"


def _start_seconds_from_url(url: str) -> int | None:
    """The start-time hint in a YouTube URL's ``t=`` or ``start=`` param.

    YouTube writes ``t=95``, ``t=95s`` and ``t=1h2m3s`` (and embeds use
    ``start=95``); all are covered by the video type's unit/bare-seconds
    grammar. ``t=0`` means "from the beginning" — no hint. A malformed value
    abstains rather than guessing.
    """
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return None
    for param in ("t", "start"):
        for value in query.get(param, []):
            seconds = parse_start_time(value)
            if seconds:
                return seconds
    return None


YOUTUBE: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="youtube",
    label="YouTube",
    source_type=SourceType.VIDEO,
    url_pattern=_URL_PATTERN,
    id_pattern=re.compile(r"[A-Za-z0-9_-]{11}"),
    canonical_url=_canonical_url,
    example_identifier="dQw4w9WgXcQ",
    root_seed=RootSeed(
        name="YouTube",
        homepage_url="https://www.youtube.com/",
        # youtu.be is deliberately NOT a recognition host: every youtu.be
        # video URL resolves through the scheme extractor before host
        # matching, so the root owns only its homepage-derived host.
        recognition_hosts=("youtube.com",),
    ),
    deep_link=_deep_link,
    start_seconds_from_url=_start_seconds_from_url,
)
