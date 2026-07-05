"""Tests for the extraction module (ISBN classification + Open Library fetch)."""

import json
from email.message import Message
from http.client import HTTPResponse
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from apps.citation.extraction import (
    ExtractionDraft,
    ExtractionResult,
    classify_input,
    extract_isbn,
    normalize_isbn,
)
from apps.citation.test_factories import make_citation_source

pytestmark = pytest.mark.django_db


def _draft(result: ExtractionResult) -> ExtractionDraft:
    assert result.draft is not None
    return result.draft


def _headers() -> Message:
    return Message()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyInput:
    def test_classify_isbn_13(self):
        result = classify_input("9780596517748")
        assert result == ("isbn", "9780596517748")

    def test_classify_isbn_10(self):
        result = classify_input("0596517742")
        assert result == ("isbn", "0596517742")

    def test_classify_isbn_with_hyphens(self):
        result = classify_input("978-0-596-51774-8")
        assert result == ("isbn", "9780596517748")

    def test_classify_isbn_with_spaces(self):
        result = classify_input("978 0 596 51774 8")
        assert result == ("isbn", "9780596517748")

    def test_classify_isbn_10_with_x_check(self):
        result = classify_input("080442957X")
        assert result == ("isbn", "080442957X")

    def test_classify_isbn_10_lowercase_x(self):
        result = classify_input("080442957x")
        assert result == ("isbn", "080442957X")

    def test_classify_non_isbn_returns_none(self):
        assert classify_input("hello world") is None
        assert classify_input("12345") is None
        assert classify_input("") is None

    def test_classify_url_https(self):
        result = classify_input("https://example.com/page")
        assert result == ("url", "https://example.com/page")

    def test_classify_url_http(self):
        result = classify_input("http://example.com/page")
        assert result == ("url", "http://example.com/page")

    def test_classify_url_strips_whitespace(self):
        result = classify_input("  https://example.com/page  ")
        assert result == ("url", "https://example.com/page")

    def test_classify_bare_domain_returns_none(self):
        assert classify_input("example.com") is None

    def test_classify_url_no_hostname_returns_none(self):
        assert classify_input("https://") is None

    def test_classify_url_empty_authority_returns_none(self):
        assert classify_input("http:///foo") is None

    def test_classify_isbn_wins_over_url(self):
        # ISBNs are digits only, so they can't start with http — but verify
        # the priority: ISBN check runs first.
        result = classify_input("9780596517748")
        assert result is not None
        assert result[0] == "isbn"


class TestNormalizeIsbn:
    def test_strips_hyphens(self):
        assert normalize_isbn("978-0-596-51774-8") == "9780596517748"

    def test_strips_spaces(self):
        assert normalize_isbn("978 0 596 51774 8") == "9780596517748"

    def test_isbn_13_digits(self):
        assert normalize_isbn("9780596517748") == "9780596517748"

    def test_isbn_10_digits(self):
        assert normalize_isbn("0596517742") == "0596517742"

    def test_isbn_10_with_x(self):
        assert normalize_isbn("080442957X") == "080442957X"

    def test_uppercases_x(self):
        assert normalize_isbn("080442957x") == "080442957X"

    def test_rejects_short(self):
        assert normalize_isbn("12345") is None

    def test_rejects_non_numeric(self):
        assert normalize_isbn("abcdefghij") is None

    def test_rejects_empty(self):
        assert normalize_isbn("") is None


# ---------------------------------------------------------------------------
# Extraction — helpers
# ---------------------------------------------------------------------------


def _make_urlopen_response(data: dict[str, Any], status: int = 200) -> MagicMock:
    """Build a mock HTTPResponse that behaves like urllib's urlopen return."""
    body = json.dumps(data).encode()
    resp = MagicMock(spec=HTTPResponse)
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


EDITION_DATA = {
    "title": "Learning Python",
    "publishers": ["O'Reilly Media"],
    "publish_date": "2009",
    "authors": [{"key": "/authors/OL34184A"}],
}

AUTHOR_DATA = {
    "name": "Mark Lutz",
}


# ---------------------------------------------------------------------------
# Extraction — happy paths
# ---------------------------------------------------------------------------


class TestExtractIsbnHappyPaths:
    def test_existing_match(self):
        """DB has a source with that ISBN → returns match, no HTTP."""
        src = make_citation_source(
            name="Learning Python",
            source_type="book",
            isbn="9780596517748",
        )
        result = extract_isbn("9780596517748")
        assert result.match == {
            "id": src.id,
            "name": "Learning Python",
            "source_type": "book",
            "skip_locator": False,
        }
        assert result.draft is None
        assert result.error is None

    @patch("apps.citation.extraction.cache")
    def test_cache_hit(self, mock_cache):
        """Cached draft → returns it, no HTTP."""
        cached_draft = ExtractionDraft(
            name="Learning Python",
            source_type="book",
            author="Mark Lutz",
            publisher="O'Reilly Media",
            year=2009,
            isbn="9780596517748",
        )
        cached_result = ExtractionResult(
            draft=cached_draft, confidence="high", source_api="openlibrary"
        )
        mock_cache.get.return_value = cached_result
        result = extract_isbn("9780596517748")
        draft = _draft(result)
        assert draft.name == "Learning Python"
        assert draft.author == "Mark Lutz"
        mock_cache.get.assert_called_once_with("extract:v3:isbn:9780596517748")

    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_openlibrary_success(self, mock_urlopen, mock_cache):
        """Both edition + author fetch succeed → full draft."""
        mock_cache.get.return_value = None
        mock_urlopen.side_effect = [
            _make_urlopen_response(EDITION_DATA),
            _make_urlopen_response(AUTHOR_DATA),
        ]
        result = extract_isbn("9780596517748")
        draft = _draft(result)
        assert draft.name == "Learning Python"
        assert draft.source_type == "book"
        assert draft.author == "Mark Lutz"
        assert draft.publisher == "O'Reilly Media"
        assert draft.year == 2009
        assert draft.isbn == "9780596517748"
        assert result.confidence == "high"
        assert result.source_api == "openlibrary"
        assert result.error is None

    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_caches_result(self, mock_urlopen, mock_cache):
        """After successful fetch, cache.set is called with 7-day TTL."""
        mock_cache.get.return_value = None
        mock_urlopen.side_effect = [
            _make_urlopen_response(EDITION_DATA),
            _make_urlopen_response(AUTHOR_DATA),
        ]
        extract_isbn("9780596517748")
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "extract:v3:isbn:9780596517748"
        assert call_args[0][2] == 60 * 60 * 24 * 7  # 7 days


# ---------------------------------------------------------------------------
# Extraction — partial failure (author fetch fails, edition succeeds)
# ---------------------------------------------------------------------------


class TestExtractIsbnPartialFailure:
    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_author_timeout(self, mock_urlopen, mock_cache):
        """Edition succeeds, author times out → draft with author=""."""
        mock_cache.get.return_value = None
        mock_urlopen.side_effect = [
            _make_urlopen_response(EDITION_DATA),
            TimeoutError("timed out"),
        ]
        result = extract_isbn("9780596517748")
        assert result.draft is not None
        assert result.draft.author == ""
        assert result.draft.name == "Learning Python"
        assert result.error is None

    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_author_404(self, mock_urlopen, mock_cache):
        """Edition succeeds, author 404 → draft with author=""."""
        mock_cache.get.return_value = None

        err = HTTPError(
            url="https://openlibrary.org/authors/OL34184A.json",
            code=404,
            msg="Not Found",
            hdrs=_headers(),
            fp=BytesIO(b""),
        )
        mock_urlopen.side_effect = [
            _make_urlopen_response(EDITION_DATA),
            err,
        ]
        result = extract_isbn("9780596517748")
        err.close()
        assert result.draft is not None
        assert result.draft.author == ""
        assert result.draft.name == "Learning Python"
        assert result.error is None

    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_no_authors_in_edition(self, mock_urlopen, mock_cache):
        """Edition has no authors key → draft with author=""."""
        mock_cache.get.return_value = None
        edition_no_authors = {
            "title": "Learning Python",
            "publishers": ["O'Reilly Media"],
            "publish_date": "2009",
        }
        mock_urlopen.side_effect = [
            _make_urlopen_response(edition_no_authors),
        ]
        result = extract_isbn("9780596517748")
        assert result.draft is not None
        assert result.draft.author == ""
        assert result.error is None


# ---------------------------------------------------------------------------
# Extraction — total failure (edition fetch fails)
# ---------------------------------------------------------------------------


class TestExtractIsbnTotalFailure:
    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_edition_not_found(self, mock_urlopen, mock_cache):
        """Edition 404 → error='not_found'."""
        mock_cache.get.return_value = None

        err = HTTPError(
            url="https://openlibrary.org/isbn/9780596517748.json",
            code=404,
            msg="Not Found",
            hdrs=_headers(),
            fp=BytesIO(b""),
        )
        mock_urlopen.side_effect = err
        result = extract_isbn("9780596517748")
        err.close()
        assert result.error == "not_found"
        assert result.draft is None

    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_edition_timeout(self, mock_urlopen, mock_cache):
        """Edition urlopen raises socket.timeout → error='timeout'."""
        mock_cache.get.return_value = None
        mock_urlopen.side_effect = TimeoutError("timed out")
        result = extract_isbn("9780596517748")
        assert result.error == "timeout"
        assert result.draft is None

    @patch("apps.citation.extraction.cache")
    @patch("apps.citation.extraction.urlopen")
    def test_edition_bad_json(self, mock_urlopen, mock_cache):
        """Edition returns invalid JSON → error='parse_error'."""
        mock_cache.get.return_value = None
        resp = MagicMock(spec=HTTPResponse)
        resp.status = 200
        resp.read.return_value = b"not json at all"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp
        result = extract_isbn("9780596517748")
        assert result.error == "parse_error"
        assert result.draft is None
