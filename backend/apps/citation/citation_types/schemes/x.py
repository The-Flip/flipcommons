"""The X (Twitter) scheme: posts on x.com/twitter.com, keyed by status id.

A **web** scheme, deliberately — X is mixed media. A ``/status/`` URL entails
nothing about what the post holds (text, photos, video), and a scheme may
only recognize URL shapes that are guaranteed instances of its owning type
(the type-homogeneity rule; see ``docs/plans/citations/VideoCitations.md``).
TikTok passes that rule because its paths discriminate (``/video/`` vs
``/photo/``); X's don't, so its children mint as web pages: whole-post
cites with no timestamp prompt (``skip_locator``), and a genuine video post
pays the honest price of losing the start-time locator.

What the scheme still buys over bare host recognition is identity: one
platform, two full host families (``x.com`` and the legacy ``twitter.com``,
plus ``www.``/``mobile.`` prefixes), recognized identically and collapsing
to one child per numeric status id — declared as one shape spanning both
apex hosts. The username path segment is vanity, not identity: any handle in
the URL resolves to the same post, and handles get renamed, so the
identifier is the status id alone and the canonical URL is the handle-free,
rename-stable ``https://x.com/i/status/<id>`` form (itself a recognized
shape, so the canonical round-trips). ``allow_path_tail`` tolerates the
``/photo/1`` / ``/video/1`` media tails on pasted URLs.
"""

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    UrlShape,
)
from apps.citation.citation_types.vocabulary import SourceType

SCHEME: Final[SchemeSpec] = SchemeSpec(
    key="x",
    label="X (Twitter)",
    source_type=SourceType.WEB,
    url_shapes=(
        UrlShape(
            hosts=("x.com", "twitter.com"),
            subdomains=("www", "mobile"),
            # The handle-free ``/i/status`` + ``/i/web/status`` shapes, or a
            # vanity handle (1–15 word chars, X's own grammar); ``statuses``
            # is the legacy path form, which also appeared bare
            # (``twitter.com/statuses/<id>``), so the leading segment is
            # optional.
            path=r"/(?:i/web/|i/|[A-Za-z0-9_]{1,15}/)?status(?:es)?/{id}",
            allow_path_tail=True,
        ),
    ),
    id_pattern=r"\d+",
    # The handle-free, rename-stable form every X/Twitter shape collapses to.
    canonical_url_template="https://x.com/i/status/{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="X (Twitter)",
        homepage_url="https://x.com/",
        recognition_hosts=("x.com", "twitter.com"),
    ),
)
