"""The TikTok scheme: videos on tiktok.com, keyed by ``<user>/video/<id>``.

TikTok is the composite-identity stress case for the scheme contract. A
TikTok watch URL is addressed by *username and* numeric video id
(``tiktok.com/@scottdanesi/video/7106…``) — the id alone cannot rebuild a
watch URL — so the identifier is the whole contiguous path tail after ``@``:
``scottdanesi/video/7106594312292453675``. That keeps the single-``{id}``
shape contract intact (the identifier must be one contiguous substring of
the URL) at the cost of encoding the platform's path structure into the
identifier; the ``id_pattern`` enforces that structure on bare identifiers
and ``cite: tiktok:<user>/video/<id>`` specs. Known caveat: a creator rename
changes the composite, so the same video re-cited after a rename mints a
second child — accepted, since the pure-spec alternative (id only) cannot
build a canonical URL at all.

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

from typing import Final

from apps.citation.citation_types.citation_scheme_specs import (
    SchemeRootCitationSourceInfo,
    UrlShape,
)
from apps.citation.citation_types.video import VideoSchemeSpec
from apps.citation.citation_types.vocabulary import SourceType

TIKTOK: Final[VideoSchemeSpec] = VideoSchemeSpec(
    key="tiktok",
    label="TikTok",
    source_type=SourceType.VIDEO,
    url_shapes=(UrlShape(hosts=("tiktok.com",), path=r"/@{id}"),),
    # The composite identifier grammar: username, the literal ``/video/``
    # separator, then the numeric post id — shared by the URL shape's ``{id}``
    # slot and the bare-identifier fullmatch, so the two can never drift.
    id_pattern=r"[a-z0-9_.]{2,24}/video/\d+",
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
SCHEME: Final[VideoSchemeSpec] = TIKTOK
