"""ISBN classification and Open Library extraction.

Separate from ``extractors.py`` (URL recognition) — the two tiers of the
extraction architecture.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, NamedTuple, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.core.cache import cache

from apps.citation.citation_types import CitationSourceTypeValue, citation_source_type
from apps.citation.isbn import isbn_checksum_ok, normalize_isbn

__all__ = [
    "ClassifiedInput",
    "DelivererNotice",
    "ExtractionDraft",
    "ExtractionMatch",
    "ExtractionResult",
    "classify_input",
    "extract_isbn",
    "normalize_isbn",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractionDraft:
    name: str
    source_type: str  # "book" for ISBN, "web" for URL
    author: str  # common — always present, may be ""
    publisher: str  # common — always present, may be ""
    year: int | None = None  # common — semantically optional
    isbn: str | None = None  # type-specific — only book drafts
    url: str | None = None  # type-specific — only web drafts


class ExtractionMatch(TypedDict):
    id: int
    name: str
    source_type: CitationSourceTypeValue
    skip_locator: bool


class DelivererNotice(NamedTuple):
    """The structured deliverer verdict an extract response carries.

    Never an error string — the frontend branches on it: ``message`` renders
    as the teaching notice, ``suggested_source_type`` preselects the
    authored-work form's type (``None`` = mixed storefront, let the user
    pick). ``suggested_source_type`` is a citation-type key — deliberately
    open vocabulary, not a book/video Literal (see the plan's podcast
    stress test).
    """

    label: str
    suggested_source_type: CitationSourceTypeValue | None
    message: str


@dataclass
class ExtractionResult:
    draft: ExtractionDraft | None = None
    match: ExtractionMatch | None = None
    error: str | None = None  # "not_found" | "timeout" | "api_error" | "parse_error"
    confidence: str = ""  # "high" | "low"
    source_api: str = ""  # "openlibrary"
    deliverer: DelivererNotice | None = None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class ClassifiedInput(NamedTuple):
    """Tagged classification of a citation input string."""

    kind: Literal["isbn", "url"]
    value: str


# An ISBN-shaped token inside free text: an ISBN-13 (978/979 prefix) or an
# ISBN-10, with optional single space/hyphen separators between digits, not
# butted against other alphanumerics. Candidates are checksum-gated by the
# caller, so a coincidental digit run never triggers a lookup.
_EMBEDDED_ISBN_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"(97[89][ -]?(?:\d[ -]?){9}\d|(?:\d[ -]?){9}[\dXx])"
    r"(?![0-9A-Za-z])"
)


def _embedded_isbn_in_text(text: str) -> str | None:
    """A checksum-valid ISBN found anywhere in *text*, or ``None``.

    The capture-ergonomics loosening (Zotero's add-by-identifier wand accepts
    messy input): a paste like ``"Pinball Compendium 978-0764325847 — first
    edition"`` should look the book up, not dead-end. Stricter than the
    whole-input path on purpose — a **mined** candidate must pass the
    checksum, because free text is full of coincidental digit runs, while a
    whole-input ISBN keeps the lenient shape-only contract (a hand-typed typo
    should reach Open Library and fail loudly, not be reclassified as text).
    """
    for match in _EMBEDDED_ISBN_RE.finditer(text):
        isbn = normalize_isbn(match.group(1))
        if isbn is not None and isbn_checksum_ok(isbn):
            return isbn
    return None


def classify_input(raw: str) -> ClassifiedInput | None:
    """Determine what kind of evidence *raw* is.

    Returns a :class:`ClassifiedInput` with ``kind`` of ``"isbn"`` or
    ``"url"``, or ``None`` if neither matches. Precedence: a whole-input ISBN
    always wins; then a URL (explicit ``http(s)://`` scheme); then a
    checksum-valid ISBN embedded anywhere in non-URL text. URLs are
    deliberately never mined for embedded ISBNs — a digit run in a path is
    the deliverer classification's job (``deliverers.embedded_isbn``), where
    the platform's declared shapes say which runs mean anything.
    """
    isbn = normalize_isbn(raw)
    if isbn is not None:
        return ClassifiedInput("isbn", isbn)
    stripped = raw.strip()
    if stripped.startswith(("http://", "https://")) and urlparse(stripped).hostname:
        return ClassifiedInput("url", stripped)
    embedded = _embedded_isbn_in_text(stripped)
    if embedded is not None:
        return ClassifiedInput("isbn", embedded)
    return None


# ---------------------------------------------------------------------------
# Open Library fetch
# ---------------------------------------------------------------------------

_OL_TIMEOUT = 4  # seconds for edition request
_WALL_CLOCK = 5  # total budget for all requests
_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days
_USER_AGENT = "Flipcommons/1.0 (citation metadata lookup)"


def _parse_year(publish_date: str) -> int | None:
    """Extract a 4-digit year from Open Library's free-form publish_date.

    Handles common formats: "2009", "June 2009", "c2009", "c.2009", "ca. 2009".
    Uses digit-boundary lookarounds instead of ``\\b`` so "c2009" (no space
    after the copyright prefix) still matches.
    """
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", publish_date)
    return int(m.group(1)) if m else None


def extract_isbn(isbn: str) -> ExtractionResult:
    """Look up *isbn* — local DB first, then cache, then Open Library."""
    from apps.citation.models import CitationSource

    # 1. Match check — already in our DB?
    existing = CitationSource.objects.filter(isbn=isbn).first()
    if existing:
        return ExtractionResult(
            match={
                "id": existing.pk,
                "name": existing.name,
                "source_type": citation_source_type(existing.source_type),
                "skip_locator": existing.skip_locator,
            }
        )

    # 2. Cache check
    cache_key = f"extract:v3:isbn:{isbn}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cast(ExtractionResult, cached)

    # 3. Open Library fetch
    deadline = time.monotonic() + _WALL_CLOCK

    # 3a. Edition request
    edition_url = f"https://openlibrary.org/isbn/{isbn}.json"
    if urlparse(edition_url).scheme != "https":
        return ExtractionResult(error="api_error")
    try:
        req = Request(edition_url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 — scheme checked above
        with urlopen(req, timeout=_OL_TIMEOUT) as resp:  # noqa: S310 — scheme checked above
            edition = json.loads(resp.read())
    except HTTPError as exc:
        if exc.code == 404:
            return ExtractionResult(error="not_found")
        return ExtractionResult(error="api_error")
    except TimeoutError, URLError:
        return ExtractionResult(error="timeout")
    except json.JSONDecodeError, ValueError:
        return ExtractionResult(error="parse_error")

    title = edition.get("title", "")
    publishers = edition.get("publishers", [])
    publisher = publishers[0] if publishers else ""
    year = _parse_year(edition.get("publish_date", ""))

    # 3b. Author request (non-fatal)
    author = ""
    author_keys = edition.get("authors", [])
    if author_keys:
        remaining = deadline - time.monotonic()
        author_timeout = max(remaining, 0.5)
        author_key = author_keys[0].get("key", "")
        author_url = f"https://openlibrary.org{author_key}.json" if author_key else ""
        if author_url and urlparse(author_url).scheme == "https":
            try:
                req = Request(author_url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 — scheme checked above
                with urlopen(req, timeout=author_timeout) as resp:  # noqa: S310 — scheme checked above
                    author_data = json.loads(resp.read())
                author = author_data.get("name", "")
            except Exception:
                logger.warning("Author fetch failed for %s", author_url, exc_info=True)

    # 4. Build draft
    draft = ExtractionDraft(
        name=title,
        source_type="book",
        author=author,
        publisher=publisher,
        year=year,
        isbn=isbn,
    )
    result = ExtractionResult(draft=draft, confidence="high", source_api="openlibrary")

    # 5. Cache it
    cache.set(cache_key, result, _CACHE_TTL)

    return result
