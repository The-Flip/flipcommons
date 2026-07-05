"""The YouTube scheme: videos on youtube.com, keyed by 11-char video id.

YouTube's one video id is reachable through many URL shapes — ``watch?v=``,
``youtu.be/``, ``/shorts/``, ``/embed/``, ``/live/``, mobile ``m.`` — all
collapsing to one canonical child, declared here as three ``UrlShape`` rows.
``youtu.be`` is a redirect-style share host: its URLs resolve through the
scheme extractor, but it is deliberately NOT a recognition host, so the
platform root owns only its homepage-derived host.

A video scheme (:class:`~apps.citation.citation_types.video.VideoSchemeSpec`):
children mint as ``video`` sources, a pasted ``?t=``/``?start=`` start time
surfaces as a structured start-seconds hint at recognition, and the deep-link
template builds the watch URL that jumps to a cited moment.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    StartSecondsSource,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

YOUTUBE: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="youtube",
    label="YouTube",
    source_type=SourceType.VIDEO,
    url_shapes=(
        UrlShape(
            hosts=("youtube.com",),
            subdomains=("www", "m"),
            path=r"/watch",
            query_id_param="v",
        ),
        UrlShape(
            hosts=("youtube.com",),
            subdomains=("www", "m"),
            path=r"/(?:embed|shorts|live)/{id}",
        ),
        UrlShape(hosts=("youtu.be",), path=r"/{id}"),
    ),
    id_pattern=r"[A-Za-z0-9_-]{11}",
    canonical_url_template="https://www.youtube.com/watch?v={identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="YouTube",
        homepage_url="https://www.youtube.com/",
        # youtu.be is deliberately NOT a recognition host: every youtu.be
        # video URL resolves through the scheme extractor before host
        # matching, so the root owns only its homepage-derived host.
        recognition_hosts=("youtube.com",),
    ),
    deep_link_template="https://www.youtube.com/watch?v={identifier}&t={start_seconds}s",
    # YouTube writes ``t=95``, ``t=95s``, ``t=1h2m3s`` and embeds use
    # ``start=95``; the video type's grammar parses them. ``t=0`` abstains.
    start_seconds_source=StartSecondsSource("query", ("t", "start")),
)
