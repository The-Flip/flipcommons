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
in the same unit grammar the video type already parses. The deep-link
template builds the fragment form; ``start_seconds_source`` reads it.
"""

import re
from typing import Final

from apps.citation.citation_types.base import (
    SchemeRootCitationSourceInfo,
    SourceType,
    StartSecondsSource,
)
from apps.citation.citation_types.url_patterns import ID_BOUNDARY, host_prefix
from apps.citation.citation_types.video import VideoSchemeSpec

# Watch-shape boundary: the id may be followed by an unlisted hex hash segment
# and/or a single trailing slash, then only query/fragment/end. Custom (not
# ID_BOUNDARY) because of the optional hash segment.
_WATCH_ID = r"(\d+)(?=(?:/[0-9a-f]{6,16})?/?(?:[?#]|$))"
# Embed URLs carry no hash segment (it rides as a ``?h=`` query param, which
# ID_BOUNDARY already tolerates), so the standard boundary applies.
_EMBED_ID = rf"(\d+){ID_BOUNDARY}"

_URL_PATTERN = re.compile(
    r"(?:"
    rf"{host_prefix('vimeo.com')}/{_WATCH_ID}"
    rf"|{host_prefix('player.vimeo.com', subdomains=())}/video/{_EMBED_ID}"
    r")"
)


VIMEO: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="vimeo",
    label="Vimeo",
    source_type=SourceType.VIDEO,
    url_pattern=_URL_PATTERN,
    id_pattern=re.compile(r"\d+"),
    canonical_url_template="https://vimeo.com/{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="Vimeo",
        homepage_url="https://vimeo.com/",
        # player.vimeo.com is deliberately NOT listed: it is a subdomain of
        # vimeo.com, so host-suffix recognition already resolves it.
        recognition_hosts=("vimeo.com",),
    ),
    # Vimeo's seek syntax is a fragment, not a query param: ``#t=95s``.
    deep_link_template="https://vimeo.com/{identifier}#t={start_seconds}s",
    # The start time rides the same way (``#t=90s``, ``#t=1m30s``).
    start_seconds_source=StartSecondsSource("fragment", ("t",)),
)
