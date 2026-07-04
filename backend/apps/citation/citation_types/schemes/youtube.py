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

from apps.citation.citation_types.base import RootSeed, SourceType
from apps.citation.citation_types.url_patterns import ID_BOUNDARY, host_prefix
from apps.citation.citation_types.video import VideoSchemeSpec, seconds_from_query

_ID = r"[A-Za-z0-9_-]{11}"
# The path shapes end at a trailing-slash/query/fragment/end (ID_BOUNDARY), so a
# malformed URL fails instead of collapsing to a wrong-but-valid-looking id.
_PATH_ID = rf"({_ID}){ID_BOUNDARY}"
_YOUTUBE = host_prefix("youtube.com", subdomains=("www", "m"))
_YOUTU_BE = host_prefix("youtu.be")

_URL_PATTERN = re.compile(
    r"(?:"
    # watch?v=: read v= from the query only (the param scan can't cross # into
    # the fragment), and the 11-char id can't continue into a longer token.
    rf"{_YOUTUBE}/watch\?(?:[^\s#]*&)?v=({_ID})(?![A-Za-z0-9_-])"
    rf"|{_YOUTUBE}/(?:embed|shorts|live)/{_PATH_ID}"
    rf"|{_YOUTU_BE}/{_PATH_ID}"
    r")"
)


def _canonical_url(video_id: str) -> str:
    """The one URL every YouTube shape collapses to."""
    return f"https://www.youtube.com/watch?v={video_id}"


def _deep_link(video_id: str, start_seconds: int) -> str:
    """The watch URL that starts playback at *start_seconds*."""
    return f"https://www.youtube.com/watch?v={video_id}&t={start_seconds}s"


YOUTUBE: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="youtube",
    label="YouTube",
    source_type=SourceType.VIDEO,
    url_pattern=_URL_PATTERN,
    id_pattern=re.compile(_ID),
    canonical_url=_canonical_url,
    root_seed=RootSeed(
        name="YouTube",
        homepage_url="https://www.youtube.com/",
        # youtu.be is deliberately NOT a recognition host: every youtu.be
        # video URL resolves through the scheme extractor before host
        # matching, so the root owns only its homepage-derived host.
        recognition_hosts=("youtube.com",),
    ),
    deep_link=_deep_link,
    # YouTube writes ``t=95``, ``t=95s``, ``t=1h2m3s`` and embeds use
    # ``start=95``; all pass through the video type's grammar. ``t=0`` abstains.
    start_seconds_from_url=seconds_from_query("t", "start"),
)
