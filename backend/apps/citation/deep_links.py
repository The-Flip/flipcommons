"""Server-side deep linking: point a citation link at the cited moment.

Reference-rendering surfaces ship finished URLs, so no per-scheme code exists
in the frontend — the deep link is computed here, at serialization time. The
model-blind weave itself (type parses the locator, scheme builds the jump
URL) is the pure ``scheme_deep_link`` in ``citation_types``; this module only
unwraps the model rows around it and decides *which* link may be rewritten.
"""

from __future__ import annotations

from apps.citation.citation_types import (
    is_known_scheme,
    scheme_canonical_url,
    scheme_deep_link,
)
from apps.citation.models import CitationSource


def deep_linked_url(source: CitationSource, locator: str, url: str) -> str:
    """Return *url*, deep-linked to *locator* when the scheme can jump there.

    The transform applies only when every layer cooperates, and falls back to
    the untouched *url* otherwise:

    - the instance has a locator, and *source* is a scheme child (its parent
      root carries the ``identifier_key``);
    - *url* is the scheme's canonical URL for the child's identifier — an
      ``archive`` snapshot or other extra link is never rewritten;
    - the weave itself succeeds (``scheme_deep_link``: the scheme can seek
      and the source's type parses the locator to a structured value).

    Callers must have the source's ``parent`` loaded (``select_related``) —
    this runs inside per-link loops and must not query.
    """
    if not locator or not source.identifier or source.parent is None:
        return url
    key = source.parent.identifier_key
    if not is_known_scheme(key):
        return url
    if url != scheme_canonical_url(key, source.identifier):
        return url
    return scheme_deep_link(key, source.identifier, locator) or url
