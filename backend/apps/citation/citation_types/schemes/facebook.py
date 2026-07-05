"""The Facebook Video scheme: video-specific URLs on facebook.com.

Facebook is mixed media, so this scheme only recognizes paths that are
syntactically video records: ``watch/?v=``, ``watch/live/?v=``, legacy
``video.php?v=`` and page-scoped ``/<page>/videos/<id>``. Generic posts,
permalinks, photos and opaque share redirects are left to host recognition
because their URL shape alone does not prove video evidence.

The identifier is the numeric video id, and every recognized shape collapses
to the handle-free watch URL. Facebook URLs have no declared seek parameter
here, so timestamp locators render beside the plain link.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="facebook",
    label="Facebook Video",
    source_type=SourceType.VIDEO,
    url_shapes=(
        UrlShape(
            hosts=("facebook.com",),
            subdomains=("www", "m", "mobile"),
            path=r"/watch/?",
            query_id_param="v",
        ),
        UrlShape(
            hosts=("facebook.com",),
            subdomains=("www", "m", "mobile"),
            path=r"/watch/live/?",
            query_id_param="v",
        ),
        UrlShape(
            hosts=("facebook.com",),
            subdomains=("www", "m", "mobile"),
            path=r"/video\.php",
            query_id_param="v",
        ),
        UrlShape(
            hosts=("facebook.com",),
            subdomains=("www", "m", "mobile"),
            path=r"/[A-Za-z0-9_.-]+/videos/{id}",
        ),
    ),
    id_pattern=r"\d+",
    canonical_url_template="https://www.facebook.com/watch/?v={identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="Facebook",
        homepage_url="https://www.facebook.com/",
        recognition_hosts=("facebook.com",),
    ),
)
