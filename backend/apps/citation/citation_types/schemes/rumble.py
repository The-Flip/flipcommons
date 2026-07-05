"""The Rumble scheme: videos on rumble.com, keyed by the watch-page path.

Rumble watch URLs include both a short video id and a slug in one contiguous
``v...html`` path. This scheme uses that whole path as the identifier so the
canonical reader URL can be rebuilt by pure template substitution.

Embed URLs are intentionally not recognized: they expose only the short id,
not the watch-page slug, and a pure scheme cannot perform the network lookup
needed to recover it. They therefore degrade to generic host recognition.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="rumble",
    label="Rumble",
    source_type=SourceType.VIDEO,
    url_shapes=(UrlShape(hosts=("rumble.com",), path=r"/{id}"),),
    id_pattern=r"v[a-z0-9]+(?:-[a-z0-9][a-z0-9-]*)?\.html",
    canonical_url_template="https://rumble.com/{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="Rumble",
        homepage_url="https://rumble.com/",
        recognition_hosts=("rumble.com",),
    ),
)
