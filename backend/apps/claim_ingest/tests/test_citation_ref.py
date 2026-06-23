"""Sum-type guarantees for ``CitationRef`` and the two cite-spec builders.

``CitationRef`` is a sum of :class:`WebCitationRef` / :class:`SchemeCitationRef`;
a both-set / neither-set ref is unconstructable (a static guarantee, exercised
here at runtime via the per-form field sets), and ``_parse_cite_value`` lowers a
cite spec to the variant the apply-side ``match`` then resolves without
re-deciding.
"""

import pytest

from apps.claim_ingest.patches._types import PatchError
from apps.claim_ingest.patches.parsing import _parse_cite_url, _parse_cite_value
from apps.claim_ingest.plan import SchemeCitationRef, WebCitationRef


def test_web_ref_carries_only_the_url_form() -> None:
    ref = WebCitationRef(
        url="https://example.com/p", archive_url="https://web.archive.org/x"
    )
    assert ref.url == "https://example.com/p"
    assert ref.archive_url == "https://web.archive.org/x"
    # No scheme/identifier on the web form — a both-set ref is unrepresentable.
    assert not hasattr(ref, "scheme")
    assert not hasattr(ref, "identifier")


def test_scheme_ref_carries_only_the_scheme_form() -> None:
    ref = SchemeCitationRef(scheme="ipdb", identifier="4443")
    assert ref.scheme == "ipdb"
    assert ref.identifier == "4443"
    # No url/archive on the scheme form — archive_url lives only on WebCitationRef.
    assert not hasattr(ref, "url")
    assert not hasattr(ref, "archive_url")


def test_web_archive_url_defaults_empty() -> None:
    assert WebCitationRef(url="https://example.com/p").archive_url == ""


def test_parse_cite_value_lowers_to_the_chosen_variant() -> None:
    web = _parse_cite_value("https://example.com/p", "", "ref")
    assert isinstance(web, WebCitationRef)
    assert web.url == "https://example.com/p"

    scheme = _parse_cite_value("ipdb:4443", "", "ref")
    assert isinstance(scheme, SchemeCitationRef)
    assert scheme == SchemeCitationRef(scheme="ipdb", identifier="4443")


def test_parse_cite_url_returns_web_variant_with_archive() -> None:
    ref = _parse_cite_url("https://example.com/p", "https://web.archive.org/x", "ref")
    assert isinstance(ref, WebCitationRef)
    assert ref.archive_url == "https://web.archive.org/x"


def test_parse_cite_value_rejects_a_scheme_matching_url() -> None:
    # A URL that matches a known scheme's pattern must be cited by scheme, not
    # as a web ref — the builder fork the resolve site relies on stays honest.
    with pytest.raises(PatchError, match="ipdb"):
        _parse_cite_value("https://www.ipdb.org/machine.cgi?id=4443", "", "ref")
