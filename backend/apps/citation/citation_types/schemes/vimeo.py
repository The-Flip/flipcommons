"""The Vimeo scheme: videos on vimeo.com, keyed by numeric video id.

Two declared shapes collapse to the numeric id:

- the watch page (``vimeo.com/<id>``), optionally carrying an unlisted-access
  hash as a second path segment (``vimeo.com/<id>/d0e9b81c05``) — the hash is
  an access token, not identity, so it is dropped and both forms dedup to one
  child. The hash charset is deliberately hex-only: a looser ``[a-z0-9]``
  would swallow non-video paths like ``/<id>/review``. The cost is honest —
  an unlisted video's canonical link may not be publicly viewable, but an
  unlisted video is a poor citation to begin with.
- the embed player on its own subdomain (``player.vimeo.com/video/<id>``);
  the hash rides there as a ``?h=`` query param, which recognition tolerates
  like any trailing param.

Legacy browse shapes (``/channels/<name>/<id>``, ``/groups/…``) are not
recognized; they host-resolve to the Vimeo root and degrade to a web child.

The time axis is what makes Vimeo worth its scheme slot next to YouTube: the
start position rides in the URL **fragment** (``#t=1m30s``), not the query,
in the same unit grammar the video type already parses. The deep-link
template builds the fragment form; ``start_seconds_source`` reads it.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    StartSecondsSource,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

VIMEO: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="vimeo",
    label="Vimeo",
    source_type=SourceType.VIDEO,
    url_shapes=(
        # Watch page; the optional second segment is the unlisted hex hash.
        UrlShape(hosts=("vimeo.com",), path=r"/{id}(?:/[0-9a-f]{6,16})?"),
        UrlShape(hosts=("player.vimeo.com",), subdomains=(), path=r"/video/{id}"),
    ),
    id_pattern=r"\d+",
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
