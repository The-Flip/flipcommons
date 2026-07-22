"""Sum-type guarantees for ``CitationRef`` and the cite-spec builders.

``CitationRef`` is a sum of :class:`WebCitationRef` / :class:`SchemeCitationRef`
/ :class:`IsbnCitationRef`; a two-forms-at-once ref is unconstructable (a static
guarantee, exercised here at runtime via the per-form field sets), and
``_parse_cite_value`` lowers a cite spec to the variant the apply-side ``match``
then resolves without re-deciding.
"""

import pytest

from apps.claim_ingest.patches._types import PatchError
from apps.claim_ingest.patches.parsing import _parse_cite_url, _parse_cite_value
from apps.claim_ingest.plan import IsbnCitationRef, SchemeCitationRef, WebCitationRef


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


def test_isbn_ref_carries_only_the_isbn_form() -> None:
    ref = IsbnCitationRef(isbn="9781889933023")
    assert ref.isbn == "9781889933023"
    # No url/archive/scheme on the isbn form — a two-form ref is unrepresentable.
    assert not hasattr(ref, "url")
    assert not hasattr(ref, "archive_url")
    assert not hasattr(ref, "scheme")


def test_parse_cite_value_lowers_an_isbn_ref() -> None:
    ref = _parse_cite_value("isbn:978-1-889933-02-3", "", "ref")
    assert ref == IsbnCitationRef(isbn="9781889933023")


def test_parse_cite_value_canonicalizes_an_isbn_10_to_isbn_13() -> None:
    # Sources store the 13-digit form, so both spellings of one work must
    # resolve to the one source rather than minting a second identity.
    assert _parse_cite_value("isbn:0887404316", "", "ref") == IsbnCitationRef(
        isbn="9780887404313"
    )


def test_parse_cite_value_rejects_a_malformed_isbn() -> None:
    with pytest.raises(PatchError, match="isbn"):
        _parse_cite_value("isbn:97818899330", "", "ref")


def test_parse_cite_value_rejects_a_bad_isbn_check_digit() -> None:
    # A patch is machine-authored: a transposed digit must fail loudly here
    # rather than surface later as a missing source.
    with pytest.raises(PatchError, match="check digit"):
        _parse_cite_value("isbn:9781889933024", "", "ref")


def test_parse_cite_value_rejects_archive_on_an_isbn_ref() -> None:
    with pytest.raises(PatchError, match="archive"):
        _parse_cite_value("isbn:9781889933023", "https://web.archive.org/x", "ref")


def test_parse_cite_value_rejects_a_scheme_matching_url() -> None:
    # A URL that matches a known scheme's pattern must be cited by scheme, not
    # as a web ref — the builder fork the resolve site relies on stays honest.
    with pytest.raises(PatchError, match="ipdb"):
        _parse_cite_value("https://www.ipdb.org/machine.cgi?id=4443", "", "ref")
