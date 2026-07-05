"""The Dailymotion scheme: videos on dailymotion.com, keyed by video id.

Dailymotion's public watch page is ``/video/<id>`` and its embed player uses
``/embed/video/<id>``; the short ``dai.ly/<id>`` share host carries the same
identifier and collapses to the watch-page canonical URL. Slugged watch URLs
are deliberately left to host recognition for now: the scheme framework's
identifier boundary guard correctly rejects ``_`` tails, and a pure scheme
should not loosen that guard for every platform just to strip Dailymotion's
display slug.

Dailymotion URLs have no declared seek parameter here, so timestamp locators
render as text beside the canonical link.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="dailymotion",
    label="Dailymotion",
    source_type=SourceType.VIDEO,
    url_shapes=(
        UrlShape(
            hosts=("dailymotion.com",),
            subdomains=("www",),
            path=r"/video/{id}",
        ),
        UrlShape(
            hosts=("dailymotion.com",),
            subdomains=("www",),
            path=r"/embed/video/{id}",
        ),
        UrlShape(hosts=("dai.ly",), path=r"/{id}"),
    ),
    id_pattern=r"x[0-9a-z]+",
    canonical_url_template="https://www.dailymotion.com/video/{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="Dailymotion",
        homepage_url="https://www.dailymotion.com/",
        # dai.ly is deliberately NOT a recognition host: short video URLs
        # resolve through the scheme extractor before host matching.
        recognition_hosts=("dailymotion.com",),
    ),
)
