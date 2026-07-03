"""Tests for URL metadata extraction."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.citation.extractors import Recognition, RecognitionChild
from apps.citation.safe_fetch import FetchResponse, SSRFBlockedError
from apps.citation.url_extraction import PageMeta, extract_url, parse_page_meta

pytestmark = pytest.mark.django_db


def _draft_name(result):
    assert result.draft is not None
    return result.draft


# ---------------------------------------------------------------------------
# _MetaParser — TDD (these define the parser's behavior)
# ---------------------------------------------------------------------------


class TestMetaParser:
    def test_og_tags_present(self):
        html = """
        <html><head>
            <meta property="og:title" content="Pinball History">
            <meta property="og:site_name" content="Wikipedia">
            <title>Pinball - Wikipedia</title>
        </head><body></body></html>
        """
        meta = parse_page_meta(html)
        assert meta.og_title == "Pinball History"
        assert meta.og_site_name == "Wikipedia"
        assert meta.title == "Pinball - Wikipedia"

    def test_only_title_tag(self):
        html = "<html><head><title>Simple Page</title></head><body></body></html>"
        meta = parse_page_meta(html)
        assert meta.title == "Simple Page"
        assert meta.og_title == ""
        assert meta.og_site_name == ""

    def test_only_og_tags(self):
        html = """
        <html><head>
            <meta property="og:title" content="OG Only">
        </head><body></body></html>
        """
        meta = parse_page_meta(html)
        assert meta.og_title == "OG Only"
        assert meta.title == ""

    def test_no_head_tag(self):
        html = "<html><body><p>No head</p></body></html>"
        meta = parse_page_meta(html)
        assert meta.title == ""
        assert meta.og_title == ""

    def test_stops_at_body(self):
        html = """
        <html><head>
            <title>Head Title</title>
        </head><body>
            <meta property="og:title" content="Should not be seen">
        </body></html>
        """
        meta = parse_page_meta(html)
        assert meta.title == "Head Title"
        assert meta.og_title == ""

    def test_stops_at_close_head(self):
        html = """
        <html><head>
            <title>In Head</title>
        </head>
        <meta property="og:title" content="After head">
        <body></body></html>
        """
        meta = parse_page_meta(html)
        assert meta.title == "In Head"
        assert meta.og_title == ""

    def test_malformed_html_missing_close_head(self):
        """Parser handles missing </head> — stops at <body>."""
        html = "<html><head><title>OK</title><meta property='og:title' content='OG'><body></body>"
        meta = parse_page_meta(html)
        assert meta.title == "OK"
        assert meta.og_title == "OG"

    def test_title_with_whitespace(self):
        html = "<html><head><title>  Spaced  Title  </title></head></html>"
        meta = parse_page_meta(html)
        assert meta.title == "Spaced  Title"

    def test_empty_html(self):
        meta = parse_page_meta("")
        assert meta == PageMeta()

    def test_meta_with_name_attribute(self):
        """Some sites use name= instead of property= for OG tags."""
        html = '<html><head><meta name="og:title" content="Name Attr"></head></html>'
        meta = parse_page_meta(html)
        assert meta.og_title == "Name Attr"

    def test_title_with_entities(self):
        html = "<html><head><title>Tom &amp; Jerry</title></head></html>"
        meta = parse_page_meta(html)
        assert meta.title == "Tom & Jerry"


# ---------------------------------------------------------------------------
# Encoding detection and fallback
# ---------------------------------------------------------------------------


class TestEncoding:
    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_explicit_charset(self, mock_cache, mock_rec, mock_fetch):
        """Content-Type with explicit charset is respected."""
        mock_cache.get.return_value = None
        # ISO-8859-1 encoded body with a non-ASCII character (ü = 0xFC)
        body = b"<html><head><title>Gew\xfcrztr\xe4ger</title></head></html>"
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html; charset=iso-8859-1"},
            body=body,
        )
        result = extract_url("https://example.com/page")
        assert _draft_name(result).name == "Gewürzträger"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_no_charset_defaults_to_utf8(self, mock_cache, mock_rec, mock_fetch):
        """Content-Type with no charset falls back to UTF-8."""
        mock_cache.get.return_value = None
        body = "<html><head><title>Ünïcödé</title></head></html>".encode()
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=body,
        )
        result = extract_url("https://example.com/page")
        assert _draft_name(result).name == "Ünïcödé"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_decode_error_falls_back_to_latin1(self, mock_cache, mock_rec, mock_fetch):
        """Body that fails declared charset falls back to latin-1."""
        mock_cache.get.return_value = None
        # Claim UTF-8 but send raw latin-1 bytes (0xFC is invalid UTF-8 lead byte)
        body = b"<html><head><title>Caf\xe9</title></head></html>"
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
        )
        result = extract_url("https://example.com/page")
        assert _draft_name(result).name == "Café"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_bogus_charset_falls_back_to_latin1(self, mock_cache, mock_rec, mock_fetch):
        """Unrecognized charset name triggers LookupError → latin-1 fallback."""
        mock_cache.get.return_value = None
        body = b"<html><head><title>Hello</title></head></html>"
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html; charset=not-a-real-encoding"},
            body=body,
        )
        result = extract_url("https://example.com/page")
        assert _draft_name(result).name == "Hello"


# ---------------------------------------------------------------------------
# extract_url — error mapping (TDD)
# ---------------------------------------------------------------------------


class TestExtractUrlErrors:
    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_ssrf_blocked(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.side_effect = SSRFBlockedError("http://localhost/", "127.0.0.1")
        result = extract_url("http://localhost/admin")
        assert result.error == "blocked"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_timeout(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.side_effect = TimeoutError("timed out")
        result = extract_url("https://slow.example.com")
        assert result.error == "timeout"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_connection_error(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.side_effect = ConnectionError("refused")
        result = extract_url("https://down.example.com")
        assert result.error == "timeout"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_dns_failure(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.side_effect = OSError("Name resolution failed")
        result = extract_url("https://nonexistent.invalid")
        assert result.error == "timeout"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_404_not_found(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=404,
            headers={"content-type": "text/html"},
            body=b"Not Found",
        )
        result = extract_url("https://example.com/missing")
        assert result.error == "not_found"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_server_error(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=500,
            headers={"content-type": "text/html"},
            body=b"Server Error",
        )
        result = extract_url("https://example.com/error")
        assert result.error == "api_error"


# ---------------------------------------------------------------------------
# extract_url — recognition match check
# ---------------------------------------------------------------------------


class TestExtractUrlRecognition:
    @patch("apps.citation.url_extraction.recognize_url")
    def test_child_match_returns_match(self, mock_rec):
        """Recognition finds a specific child → return match directly."""
        mock_rec.return_value = Recognition(
            parent_id=20,
            parent_name="IPDB",
            child=RecognitionChild(
                id=42, name="IPDB #4836", skip_locator=True, source_type="web"
            ),
        )
        result = extract_url("https://www.ipdb.org/machine.cgi?id=4836")
        assert result.match == {
            "id": 42,
            "name": "IPDB #4836",
            "source_type": "web",
            "skip_locator": True,
        }
        assert result.draft is None

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url")
    @patch("apps.citation.url_extraction.cache")
    def test_domain_only_match_ignored(self, mock_cache, mock_rec, mock_fetch):
        """Domain-only recognition (no child) proceeds to fetch."""
        mock_rec.return_value = Recognition(
            parent_id=30,
            parent_name="Jersey Jack",
        )
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html><head><title>Some Page</title></head></html>",
        )
        result = extract_url("https://jerseyjackpinball.com/products/foo")
        assert result.draft is not None
        assert result.draft.name == "Some Page"
        assert result.match is None


# ---------------------------------------------------------------------------
# extract_url — cache
# ---------------------------------------------------------------------------


class TestExtractUrlCache:
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_cache_hit(self, mock_cache, mock_rec):
        from apps.citation.extraction import ExtractionDraft, ExtractionResult

        cached = ExtractionResult(
            draft=ExtractionDraft(
                name="Cached",
                source_type="web",
                author="",
                publisher="",
                year=None,
                url="https://example.com",
            ),
            confidence="low",
            source_api="og_meta",
        )
        mock_cache.get.return_value = cached
        result = extract_url("https://example.com")
        assert _draft_name(result).name == "Cached"
        mock_cache.get.assert_called_once_with("extract:v2:url:https://example.com")

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_caches_result_with_4h_ttl(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html><head><title>Test</title></head></html>",
        )
        extract_url("https://example.com")
        mock_cache.set.assert_called_once()
        assert mock_cache.set.call_args[0][2] == 60 * 60 * 4


# ---------------------------------------------------------------------------
# extract_url — successful scrape
# ---------------------------------------------------------------------------


class TestExtractUrlSuccess:
    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_og_title_and_site_name(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=b"""<html><head>
                <meta property="og:title" content="Pinball History">
                <meta property="og:site_name" content="Wikipedia">
                <title>Pinball - Wikipedia</title>
            </head><body></body></html>""",
        )
        result = extract_url("https://en.wikipedia.org/wiki/Pinball")
        draft = _draft_name(result)
        assert draft.name == "Pinball History"
        assert draft.publisher == "Wikipedia"
        assert draft.source_type == "web"
        assert draft.url == "https://en.wikipedia.org/wiki/Pinball"
        assert result.confidence == "low"
        assert result.source_api == "og_meta"

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_fallback_to_title_tag(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html><head><title>Just Title</title></head></html>",
        )
        result = extract_url("https://example.com/page")
        draft = _draft_name(result)
        assert draft.name == "Just Title"
        assert draft.publisher == ""

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_no_title_leaves_name_empty(self, mock_cache, mock_rec, mock_fetch):
        # No og:title and no <title>: name is empty (not the URL), so the create
        # form prompts the user to name the page instead of prefilling a URL.
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html><head></head><body></body></html>",
        )
        result = extract_url("https://example.com/bare")
        assert _draft_name(result).name == ""

    @patch("apps.citation.url_extraction.safe_fetch")
    @patch("apps.citation.url_extraction.recognize_url", return_value=None)
    @patch("apps.citation.url_extraction.cache")
    def test_non_html_content_type(self, mock_cache, mock_rec, mock_fetch):
        mock_cache.get.return_value = None
        mock_fetch.return_value = FetchResponse(
            status=200,
            headers={"content-type": "application/pdf"},
            body=b"%PDF-1.4...",
        )
        result = extract_url("https://example.com/doc.pdf")
        # Non-HTML: no parseable title, so name is empty (not the URL).
        draft = _draft_name(result)
        assert draft.name == ""
        assert draft.source_type == "web"
