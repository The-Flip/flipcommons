"""Server-side deep linking: point a citation link at the cited moment.

Reference-rendering surfaces ship finished URLs, so no per-scheme code exists
in the frontend — a scheme's ``deep_link`` builder runs here, at serialization
time. The transform composes the two plugin layers without naming either: the
cited source's *type* parses the locator into its structured value (video:
seconds), and the source's *scheme* builds the jump URL from it.
"""

from __future__ import annotations

from apps.citation.citation_types import SCHEME_SPECS, citation_type_spec
from apps.citation.models import CitationSource


def deep_linked_url(source: CitationSource, locator: str, url: str) -> str:
    """Return *url*, deep-linked to *locator* when the scheme can jump there.

    The transform applies only when every layer cooperates, and falls back to
    the untouched *url* otherwise:

    - the instance has a locator, and *source* is a scheme child (its parent
      root carries the ``identifier_key``);
    - *url* is the scheme's canonical URL for the child's identifier — an
      ``archive`` snapshot or other extra link is never rewritten;
    - the scheme has a ``deep_link`` builder and the source's type contract
      parses the locator to a structured value.

    Callers must have the source's ``parent`` loaded (``select_related``) —
    this runs inside per-link loops and must not query.
    """
    if not locator or not source.identifier or source.parent is None:
        return url
    spec = SCHEME_SPECS.get(source.parent.identifier_key)
    if spec is None or spec.deep_link is None:
        return url
    if url != spec.canonical_url(source.identifier):
        return url
    parse_value = citation_type_spec(source.source_type).locator.parse_value
    if parse_value is None:
        return url
    value = parse_value(locator)
    if value is None:
        return url
    return spec.deep_link(source.identifier, value)
