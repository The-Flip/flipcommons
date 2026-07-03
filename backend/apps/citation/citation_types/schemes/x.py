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
to one child per numeric status id. The ``root_seed`` declares **both** apex
hosts — the first multi-host root. The username path segment is vanity, not
identity: any handle in the URL resolves to the same post, and handles get
renamed, so the identifier is the status id alone and the canonical URL is
the handle-free, rename-stable ``https://x.com/i/status/<id>`` form (itself
a recognized shape, so the canonical round-trips). Trailing ``/photo/1`` /
``/video/1`` segments on pasted URLs are tolerated after the id.
"""

import re
from typing import Final

from apps.citation.citation_types.base import RootSeed, SchemeSpec, SourceType

_URL_PATTERN = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/"
    # The handle-free ``/i/status`` + ``/i/web/status`` shapes, or a vanity
    # handle (1–15 word chars, X's own grammar); ``statuses`` is the legacy
    # path form, which also appeared bare (``twitter.com/statuses/<id>``), so
    # the leading segment is optional. Boundary: the digits must end at a
    # path/query/fragment break — a ``/photo/1`` tail is fine but
    # ``…/status/123abc`` is not.
    r"(?:i/web/|i/|[A-Za-z0-9_]{1,15}/)?status(?:es)?/(\d+)(?=[/?#]|$)"
)


def _canonical_url(status_id: str) -> str:
    """The one URL every X/Twitter shape collapses to (handle-free form)."""
    return f"https://x.com/i/status/{status_id}"


X_TWITTER: Final[SchemeSpec] = SchemeSpec(
    key="x",
    label="X (Twitter)",
    source_type=SourceType.WEB,
    url_pattern=_URL_PATTERN,
    id_pattern=re.compile(r"\d+"),
    canonical_url=_canonical_url,
    example_identifier="1585341984679469056",
    root_seed=RootSeed(
        name="X (Twitter)",
        homepage_url="https://x.com/",
        recognition_hosts=("x.com", "twitter.com"),
    ),
)
