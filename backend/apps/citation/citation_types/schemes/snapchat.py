"""The Snapchat Spotlight scheme: videos on snapchat.com, keyed by token.

Spotlight share URLs under ``/spotlight/<token>`` identify individual videos
with an opaque URL-safe token. Other public Snapchat paths (profiles, add
links, stories) are not video-homogeneous enough for this video scheme and
fall through to generic web recognition.

Snapchat URLs have no declared seek parameter, so timestamp locators render as
text beside the canonical Spotlight link.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="snapchat",
    label="Snapchat",
    source_type=SourceType.VIDEO,
    url_shapes=(UrlShape(hosts=("snapchat.com",), path=r"/spotlight/{id}"),),
    id_pattern=r"[A-Za-z0-9_-]{8,200}",
    canonical_url_template="https://www.snapchat.com/spotlight/{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="Snapchat",
        homepage_url="https://www.snapchat.com/",
        recognition_hosts=("snapchat.com",),
    ),
)
