"""The Instagram Reels scheme: videos on instagram.com, keyed by shortcode.

Instagram has multiple public media paths, but only ``/reel/<shortcode>`` is
video-homogeneous enough for a video scheme. ``/p/`` can be image or video,
stories are profile-scoped ephemera, and profile URLs are generic web pages,
so those shapes deliberately fall through to host recognition instead.

Instagram URLs have no seek parameter, so the scheme declares no time
capability; cited timestamps render as locator text beside the reel link.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="instagram",
    label="Instagram Reels",
    source_type=SourceType.VIDEO,
    url_shapes=(
        UrlShape(
            hosts=("instagram.com",),
            subdomains=("www", "m"),
            path=r"/reel/{id}",
        ),
    ),
    id_pattern=r"[A-Za-z0-9_-]{5,30}",
    canonical_url_template="https://www.instagram.com/reel/{identifier}/",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="Instagram",
        homepage_url="https://www.instagram.com/",
        recognition_hosts=("instagram.com",),
    ),
)
