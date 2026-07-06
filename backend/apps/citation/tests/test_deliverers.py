"""Tests for the deliverer table: matching, ISBN extraction, messages.

Pure — no DB. The classification/guardrail integration lives in
``test_extractors.py`` and ``test_api.py``.
"""

from __future__ import annotations

import pytest

from apps.citation.deliverers import (
    DELIVERERS,
    DelivererSpec,
    _validate_and_index,
    deliverer_for_url,
    deliverer_notice_message,
    embedded_isbn,
    suggested_work_kind,
)
from apps.citation.hosts import Host, is_dns_host, normalize_host
from apps.citation.isbn import isbn_checksum_ok, normalize_isbn

# A real book (Learning Python) in both forms; the ISBN-10 check digit is 2.
ISBN13 = "9780596517748"
ISBN10 = "0596517742"
# ISBN-10-shaped but checksum-invalid (the ISBN-13's tail digits verbatim).
BAD_ISBN10 = "0596517748"


def _spec(label: str) -> DelivererSpec:
    matches = [s for s in DELIVERERS if s.label == label]
    assert len(matches) == 1
    return matches[0]


# ---------------------------------------------------------------------------
# ISBN helpers
# ---------------------------------------------------------------------------


class TestIsbnChecksum:
    @pytest.mark.parametrize(
        "isbn",
        [ISBN13, ISBN10, "0306406152", "097522980X", "9780306406157"],
    )
    def test_valid(self, isbn):
        assert isbn_checksum_ok(isbn)

    @pytest.mark.parametrize(
        "isbn",
        [BAD_ISBN10, "9780596517741", "0306406153", "12345", ""],
    )
    def test_invalid(self, isbn):
        assert not isbn_checksum_ok(isbn)

    def test_normalize_then_checksum(self):
        normalized = normalize_isbn("978-0-596-51774-8")
        assert normalized == ISBN13
        assert isbn_checksum_ok(normalized)


# ---------------------------------------------------------------------------
# Table conformance — every declaration holds the invariants the matcher
# assumes. Parametrized over the registry, like the scheme conformance suite.
# ---------------------------------------------------------------------------


class TestTableConformance:
    @pytest.mark.parametrize(
        "spec", DELIVERERS, ids=[spec.label for spec in DELIVERERS]
    )
    def test_hosts_normalized_dns(self, spec):
        for host in spec.hosts:
            assert normalize_host(host) == host
            assert is_dns_host(Host(host))

    def test_duplicate_host_rejected(self):
        specs = (
            DelivererSpec(label="A", hosts=("dupe.example",)),
            DelivererSpec(label="B", hosts=("dupe.example",)),
        )
        with pytest.raises(ValueError, match="declared twice"):
            _validate_and_index(specs)

    def test_nested_host_rejected(self):
        specs = (
            DelivererSpec(label="A", hosts=("outer.example",)),
            DelivererSpec(label="B", hosts=("inner.outer.example",)),
        )
        with pytest.raises(ValueError, match="nests under"):
            _validate_and_index(specs)

    def test_unnormalized_host_rejected(self):
        specs = (DelivererSpec(label="A", hosts=("WWW.Example.com",)),)
        with pytest.raises(ValueError, match="normalized DNS"):
            _validate_and_index(specs)

    def test_unknown_work_kind_rejected(self):
        specs = (
            DelivererSpec(label="A", hosts=("a.example",), delivers="album"),  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="unknown work kind"):
            _validate_and_index(specs)

    def test_isbn_pattern_without_group_rejected(self):
        specs = (
            DelivererSpec(
                label="A", hosts=("a.example",), isbn_path_patterns=(r"/dp/\d+",)
            ),
        )
        with pytest.raises(ValueError, match="lacks"):
            _validate_and_index(specs)


# ---------------------------------------------------------------------------
# Host matching
# ---------------------------------------------------------------------------


class TestDelivererForUrl:
    @pytest.mark.parametrize(
        ("url", "label"),
        [
            ("https://www.amazon.com/dp/B0ABC12345", "Amazon"),
            ("https://smile.amazon.de/gp/product/3161484100", "Amazon"),
            ("https://a.co/d/4WjizXn", "Amazon"),
            ("https://www.netflix.com/title/80057281", "Netflix"),
            ("https://play.max.com/movie/abc", "HBO Max"),
            ("https://www.barnesandnoble.com/w/x/1100191586", "Barnes & Noble"),
            ("https://tv.apple.com/us/movie/tilt/umc.cmc.abc", "Apple TV"),
            ("https://www.audible.com/pd/Some-Book/B0ABC12345", "Audible"),
        ],
    )
    def test_matches(self, url, label):
        spec = deliverer_for_url(url)
        assert spec is not None
        assert spec.label == label

    @pytest.mark.parametrize(
        "url",
        [
            "https://notamazon.com/dp/0596517742",  # label boundary holds
            "https://kineticist.com/article",
            "https://apple.com/support",  # only the store subdomains are declared
            "https://127.0.0.1/dp/0596517742",  # IP literal abstains
            "https://[::1/broken",  # unparseable abstains
            "notaurl",
        ],
    )
    def test_misses(self, url):
        assert deliverer_for_url(url) is None


# ---------------------------------------------------------------------------
# Embedded-ISBN extraction
# ---------------------------------------------------------------------------


class TestEmbeddedIsbn:
    @pytest.mark.parametrize(
        "url",
        [
            f"https://www.amazon.com/dp/{ISBN10}",
            f"https://www.amazon.com/Learning-Python/dp/{ISBN10}/ref=sr_1_1",
            f"https://www.amazon.co.uk/gp/product/{ISBN10}?tag=x",
            f"https://www.amazon.com/gp/aw/d/{ISBN10}",
            f"https://www.amazon.com/exec/obidos/ASIN/{ISBN10}",
        ],
    )
    def test_amazon_shapes(self, url):
        assert embedded_isbn(url, _spec("Amazon")) == ISBN10

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.amazon.com/dp/B0ABC12345",  # non-book ASIN shape
            f"https://www.amazon.com/dp/{BAD_ISBN10}",  # checksum-invalid
            f"https://www.amazon.com/dp/{ISBN10}9",  # over-long token
            f"https://www.amazon.com/somewhere/{ISBN10}",  # not a product shape
            "https://www.amazon.com/gp/video/detail/B0ABC12345",
            "https://a.co/d/4WjizXn",  # opaque short link
        ],
    )
    def test_amazon_non_isbn(self, url):
        assert embedded_isbn(url, _spec("Amazon")) is None

    def test_bn_ean_param(self):
        url = f"https://www.barnesandnoble.com/w/title/1100191586?ean={ISBN13}"
        assert embedded_isbn(url, _spec("Barnes & Noble")) == ISBN13

    def test_bn_junk_ean_rejected(self):
        url = "https://www.barnesandnoble.com/w/title/1100191586?ean=1234567890123"
        assert embedded_isbn(url, _spec("Barnes & Noble")) is None

    def test_abebooks_isbn_param_and_path(self):
        spec = _spec("AbeBooks")
        assert (
            embedded_isbn(
                f"https://www.abebooks.com/servlet/SearchResults?isbn={ISBN13}", spec
            )
            == ISBN13
        )
        assert (
            embedded_isbn(f"https://www.abebooks.com/{ISBN13}/Some-Title/plp", spec)
            == ISBN13
        )


# ---------------------------------------------------------------------------
# Kind hints and messages
# ---------------------------------------------------------------------------


class TestSuggestedWorkKind:
    def test_amazon_prime_video_path(self):
        spec = _spec("Amazon")
        url = "https://www.amazon.com/gp/video/detail/B0ABC12345"
        assert suggested_work_kind(url, spec) == "video"

    def test_amazon_default_is_mixed(self):
        spec = _spec("Amazon")
        assert suggested_work_kind("https://www.amazon.com/dp/B0ABC12345", spec) is None

    @pytest.mark.parametrize(
        ("path", "kind"),
        [
            ("/store/books/details?id=x", "book"),
            ("/store/audiobooks/details?id=x", "book"),
            ("/store/movies/details?id=x", "video"),
            ("/store/apps/details?id=x", None),
        ],
    )
    def test_google_play_paths(self, path, kind):
        spec = _spec("Google Play")
        assert suggested_work_kind(f"https://play.google.com{path}", spec) == kind

    def test_host_default(self):
        spec = _spec("Netflix")
        assert suggested_work_kind("https://netflix.com/title/1", spec) == "video"


class TestNoticeMessage:
    def test_video(self):
        msg = deliverer_notice_message(_spec("Netflix"), "video")
        assert msg == (
            "Netflix delivers copies of movies and shows — cite the movie or "
            "video itself, not the Netflix page."
        )

    def test_mixed(self):
        msg = deliverer_notice_message(_spec("Amazon"), None)
        assert msg == (
            "Amazon delivers copies of works — cite the work itself (the "
            "book, movie or other work), not the Amazon page."
        )

    def test_works_phrase_override(self):
        msg = deliverer_notice_message(_spec("Audible"), "book")
        assert msg == (
            "Audible delivers audiobook editions of books — cite the book "
            "itself, not the Audible page."
        )

    def test_kind_hint_drives_wording(self):
        # The mixed Amazon spec with a video path hint reads as video.
        msg = deliverer_notice_message(_spec("Amazon"), "video")
        assert "cite the movie or video itself" in msg
