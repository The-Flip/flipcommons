"""The YouTube scheme: videos on youtube.com, keyed by 11-char video id.

YouTube's one video id is reachable through many URL shapes (``watch?v=``,
``youtu.be/``, ``/shorts/``, ``/embed/``, ``/live/``, mobile ``m.``) plus
trailing params — all collapse to one canonical child. The pattern is
host-bound on ``https?://<host>`` like the others so ``notyoutube.com`` can't
match, and ``(?![A-Za-z0-9_-])`` pins the id to 11 chars so a 12-char typo
fails instead of truncating to a wrong-but-valid-looking id.

A video scheme (:class:`~apps.citation.citation_types.video.VideoSchemeSpec`):
children mint as ``video`` sources, a pasted ``?t=``/``?start=`` start time
surfaces as a structured ``SchemeMatch.start_seconds`` hint, and ``deep_link``
builds the watch URL that jumps to a cited moment.
"""

import re
from urllib.parse import parse_qs, urlparse

from apps.citation.citation_types.base import RootSeed, SourceType
from apps.citation.citation_types.video import VideoSchemeSpec, parse_start_time


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


YOUTUBE = VideoSchemeSpec(
    key="youtube",
    label="YouTube",
    source_type=SourceType.VIDEO,
    url_pattern=re.compile(
        r"https?://(?:"
        r"(?:www\.|m\.)?youtube\.com/(?:watch\?(?:[^\s]*&)?v=|embed/|shorts/|live/)"
        r"|(?:www\.)?youtu\.be/"
        r")([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
    ),
    id_pattern=re.compile(r"[A-Za-z0-9_-]{11}"),
    canonical_url=lambda id: f"https://www.youtube.com/watch?v={id}",
    example_identifier="dQw4w9WgXcQ",
    root_seed=RootSeed(
        name="YouTube",
        homepage_url="https://www.youtube.com/",
        # youtu.be is deliberately NOT a recognition host: every youtu.be
        # video URL resolves through the scheme extractor before host
        # matching, so the root owns only its homepage-derived host.
        recognition_hosts=("youtube.com",),
    ),
    deep_link=lambda id, seconds: f"https://www.youtube.com/watch?v={id}&t={seconds}s",
    start_seconds_from_url=_start_seconds_from_url,
)
