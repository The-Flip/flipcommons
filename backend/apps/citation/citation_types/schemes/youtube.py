"""The YouTube scheme: videos on youtube.com, keyed by 11-char video id.

YouTube's one video id is reachable through many URL shapes (``watch?v=``,
``youtu.be/``, ``/shorts/``, ``/embed/``, ``/live/``, mobile ``m.``) plus
trailing params — all collapse to one canonical child. The pattern is
host-bound on ``https?://<host>`` like the others so ``notyoutube.com`` can't
match, and ``(?![A-Za-z0-9_-])`` pins the id to 11 chars so a 12-char typo
fails instead of truncating to a wrong-but-valid-looking id.
"""

import re

from apps.citation.citation_types.base import RootSeed, SchemeSpec, SourceType

YOUTUBE = SchemeSpec(
    key="youtube",
    label="YouTube",
    source_type=SourceType.WEB,
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
        recognition_hosts=("youtube.com", "youtu.be"),
    ),
)
