"""The TikTok scheme: videos on tiktok.com, keyed by ``<user>/video/<id>``.

TikTok is the composite-identity stress case for the scheme contract. A
TikTok watch URL is addressed by *username and* numeric video id
(``tiktok.com/@scottdanesi/video/7106…``) — the id alone cannot rebuild a
watch URL — so the identifier is the whole contiguous path tail after ``@``:
``scottdanesi/video/7106594312292453675``. That keeps the ``url_pattern``
single-capture contract intact (the identifier must be one contiguous
substring of the URL) at the cost of encoding the platform's path structure
into the identifier; the ``id_pattern`` enforces that structure on bare
identifiers and ``cite: tiktok:<user>/video/<id>`` specs. Known caveat: a
creator rename changes the composite, so the same video re-cited after a
rename mints a second child — accepted, since the pure-spec alternative (id
only) cannot build a canonical URL at all.

Usernames are 2–24 chars of lowercase letters, digits, ``_`` and ``.`` —
TikTok's own grammar. An uppercase paste fails extraction and degrades to a
host match rather than minting a case-variant duplicate child.

Deliberately unrecognized, both degrading to host-suffix recognition (a web
child under the TikTok root, no dedup with the canonical video):

- share short links (``vm.tiktok.com/<code>``, ``vt.tiktok.com/<code>``,
  ``tiktok.com/t/<code>``): the code is an opaque server-side redirect a
  pure, no-I/O scheme cannot resolve;
- the legacy mobile shape (``m.tiktok.com/v/<id>.html``): it carries no
  username, so the composite identifier cannot be built from it;
- photo posts (``/@user/photo/<id>``): not video evidence.

No ``deep_link_template`` and no ``start_seconds_source``: TikTok URLs have
no seek parameter, so a cited timestamp renders as locator text beside the
plain watch link — the case that made the video contract's deep link
optional.
"""

import re
from typing import Final

from apps.citation.citation_types.base import SchemeRootCitationSourceInfo, SourceType
from apps.citation.citation_types.url_patterns import ID_BOUNDARY, host_prefix
from apps.citation.citation_types.video import VideoSchemeSpec

# The composite identifier grammar: username, the literal ``/video/``
# separator, then the numeric post id. Shared by the URL capture and the
# bare-identifier fullmatch so the two can never drift.
_IDENTIFIER = r"[a-z0-9_.]{2,24}/video/\d+"

# ID_BOUNDARY: the id may be followed by a single trailing slash and then only a
# query, a fragment, or the end — never more path (``/duet`` is rejected).
_URL_PATTERN = re.compile(
    host_prefix("tiktok.com") + rf"/@({_IDENTIFIER}){ID_BOUNDARY}"
)


TIKTOK: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="tiktok",
    label="TikTok",
    source_type=SourceType.VIDEO,
    url_pattern=_URL_PATTERN,
    id_pattern=re.compile(_IDENTIFIER),
    # The composite identifier is the contiguous path tail, so the watch URL
    # rebuilds by plain substitution.
    canonical_url_template="https://www.tiktok.com/@{identifier}",
    root_citation_source_info=SchemeRootCitationSourceInfo(
        name="TikTok",
        homepage_url="https://www.tiktok.com/",
        # vm./vt. short-link hosts are subdomains of tiktok.com, so
        # host-suffix recognition already resolves them to this root.
        recognition_hosts=("tiktok.com",),
    ),
)
