"""Locator validation against the cited source's citation-type contract.

The one write-path chokepoint for locator text: every surface that stores a
locator — the interactive instance mint (API + claim save) and the data-patch
parser — normalizes through here, so a video cite's timestamp is validated
and canonicalized no matter how it arrives. Types without a grammar
(``freeform``) pass locators through untouched.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.citation.citation_types import citation_type_driver


def normalized_locator(source_type: str, locator: str) -> str:
    """Validate and canonicalize *locator* for a source of *source_type*.

    An empty locator is always legal (a locator is optional on every type) and
    returns empty. A non-empty locator runs through the type's framework
    driver: freeform types return it unchanged; a grammar type (video)
    returns the canonical form or raises ``ValidationError`` keyed on
    ``locator`` with the contract's contributor-facing message.
    """
    if not locator:
        return ""
    driver = citation_type_driver(source_type)
    normalized = driver.normalize_locator(locator)
    if normalized is None:
        raise ValidationError({"locator": driver.spec.locator.invalid_message})
    return normalized
