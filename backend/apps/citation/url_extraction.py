"""URL metadata extraction — fetch page HTML and propose a citation draft.

Uses ``safe_fetch`` for SSRF protection and ``html.parser`` from stdlib
(no BeautifulSoup dependency).
"""

from __future__ import annotations

import html.parser
import logging
from dataclasses import dataclass

from django.core.cache import cache

from .deliverers import deliverer_notice_message
from .extraction import DelivererNotice, ExtractionDraft, ExtractionResult, extract_isbn
from .extractors import (
    UrlDeliverer,
    UrlIdentified,
    UrlSchemeRecord,
    UrlSiteOf,
    UrlUnrecognized,
    classify_url,
)
from .isbn import isbn_checksum_ok, normalize_isbn
from .safe_fetch import SSRFBlockedError, safe_fetch

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60 * 4  # 4 hours
_FETCH_TIMEOUT = 5  # seconds


# ---------------------------------------------------------------------------
# HTML meta parser
# ---------------------------------------------------------------------------


@dataclass
class PageMeta:
    title: str = ""
    og_title: str = ""
    og_site_name: str = ""
    # The work's ISBN when the page declares it machine-readably (Open Graph
    # book namespace or a schema.org itemprop meta). Raw as declared —
    # normalization/checksum happens at the consumer.
    isbn: str = ""


class _MetaParser(html.parser.HTMLParser):
    """Extract ``<title>``, ``og:title``, and ``og:site_name`` from ``<head>``."""

    def __init__(self) -> None:
        super().__init__()
        self.meta = PageMeta()
        self._in_title = False
        self._title_parts: list[str] = []
        self._done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag == "body":
            self._done = True
            return
        if tag == "title":
            self._in_title = True
            self._title_parts = []
            return
        if tag == "meta":
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            prop = attr_dict.get("property", "")
            name = attr_dict.get("name", "")
            itemprop = attr_dict.get("itemprop", "")
            content = attr_dict.get("content", "")
            if prop == "og:title" or name == "og:title":
                self.meta.og_title = content
            elif prop == "og:site_name" or name == "og:site_name":
                self.meta.og_site_name = content
            # The Open Graph book namespace appears both prefixed and bare in
            # the wild; schema.org Book pages use itemprop. Head-level meta
            # only — JSON-LD in the body is deliberately out of scope.
            elif (
                prop in ("og:book:isbn", "book:isbn", "books:isbn")
                or itemprop == "isbn"
            ):
                self.meta.isbn = content

    def handle_endtag(self, tag: str) -> None:
        if self._done:
            return
        if tag == "head":
            self._done = True
            return
        if tag == "title" and self._in_title:
            self._in_title = False
            self.meta.title = "".join(self._title_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._in_title and not self._done:
            self._title_parts.append(data)


def parse_page_meta(html_text: str) -> PageMeta:
    """Parse HTML and return page metadata from ``<head>``."""
    parser = _MetaParser()
    parser.feed(html_text)
    return parser.meta


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------


class _NotFoundError(Exception):
    pass


class _HttpStatusError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"HTTP {status}")


def _detect_encoding(content_type: str) -> str:
    """Detect charset from Content-Type header, falling back to utf-8."""
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip('"')
    return "utf-8"


def _fetch_page_meta(url: str) -> PageMeta:
    """Fetch *url* and parse HTML meta tags.

    Raises on network errors.  Returns empty ``PageMeta`` for non-HTML.
    """
    resp = safe_fetch(url, timeout=_FETCH_TIMEOUT)

    if resp.status < 200 or resp.status >= 300:
        if resp.status == 404:
            raise _NotFoundError()
        raise _HttpStatusError(resp.status)

    content_type = resp.headers.get("content-type", "")
    mime = content_type.split(";")[0].strip().lower()
    if mime != "text/html":
        return PageMeta()

    encoding = _detect_encoding(content_type)
    try:
        text = resp.body.decode(encoding)
    except UnicodeDecodeError, LookupError:
        text = resp.body.decode("latin-1")

    return parse_page_meta(text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _page_meta_isbn(url: str) -> str | None:
    """Fetch *url* and return a checksum-valid ISBN its head metadata declares.

    The Zotero lesson: the page often carries the identifier the URL doesn't
    (``og:book:isbn``, schema.org ``itemprop="isbn"``). Server-side, so some
    deliverers bot-block it (Amazon 503s; Zotero escapes that only by running
    in the user's browser) — any failure returns ``None`` and the caller
    degrades to the notice, never to an error.
    """
    try:
        meta = _fetch_page_meta(url)
    except SSRFBlockedError, TimeoutError, OSError, _NotFoundError, _HttpStatusError:
        return None
    if not meta.isbn:
        return None
    isbn = normalize_isbn(meta.isbn)
    if isbn is None or not isbn_checksum_ok(isbn):
        return None
    return isbn


def _extract_deliverer(url: str, verdict: UrlDeliverer) -> ExtractionResult:
    """The F4 flow for a deliverer URL: auto-classify the work, else teach.

    URL-embedded ISBN first (already checksum-gated by classification), then
    the page-metadata fallback — attempted only when the suggested kind could
    plausibly be a book (book or mixed; fetching a streaming page for an ISBN
    is pointless). Any ISBN routes through ``extract_isbn`` (Open Library +
    its existing-source match check). A lookup yielding neither match nor
    draft falls back to the teaching notice, never to a raw error.

    Uncached at this level by design: classification is pure, ``extract_isbn``
    caches its own lookups, and caching a transient fetch failure's notice
    for hours would hide a recoverable auto-classify.
    """
    isbn = verdict.isbn
    if isbn is None and verdict.kind in (None, "book"):
        isbn = _page_meta_isbn(url)
    if isbn is not None:
        result = extract_isbn(isbn)
        if result.match is not None or result.draft is not None:
            return result
    return ExtractionResult(
        deliverer=DelivererNotice(
            label=verdict.spec.label,
            suggested_source_type=verdict.kind,
            message=deliverer_notice_message(verdict.spec, verdict.kind),
        )
    )


def extract_url(url: str) -> ExtractionResult:
    """Look up *url* — classify first, then cache, then fetch."""
    # 1. Classification. A deliverer URL never reaches the scrape path — its
    # page must not become a web draft (and prod may hold a legacy
    # misclassified root its host would match). An existing child is returned
    # as a match; every other verdict falls through to the scrape, preserving
    # the pre-classification behavior (domain-only matches are intentionally
    # ignored: extraction needs a specific child so it knows which locator
    # rules apply).
    verdict = classify_url(url)
    match verdict:
        case UrlDeliverer():
            return _extract_deliverer(url, verdict)
        case UrlIdentified(child=child):
            return ExtractionResult(
                match={
                    "id": child.id,
                    "name": child.name,
                    "source_type": child.source_type,
                    "skip_locator": child.skip_locator,
                }
            )
        case UrlSchemeRecord(recognition=rec) if (
            rec is not None and rec.child is not None
        ):
            return ExtractionResult(
                match={
                    "id": rec.child.id,
                    "name": rec.child.name,
                    "source_type": rec.child.source_type,
                    "skip_locator": rec.child.skip_locator,
                }
            )
        case UrlSchemeRecord() | UrlSiteOf() | UrlUnrecognized():
            pass

    # 2. Cache check. The ``v3`` namespace pins cached drafts to the current
    # semantics (v3: deliverer URLs classify instead of scraping, so a v2
    # amazon web draft must not be served); bump it when semantics change so
    # stale drafts are abandoned rather than served.
    cache_key = f"extract:v3:url:{url}"
    cached: ExtractionResult | None = cache.get(cache_key)
    if cached is not None:
        return cached

    # 3. Fetch and parse
    try:
        meta = _fetch_page_meta(url)
    except SSRFBlockedError:
        return ExtractionResult(error="blocked")
    except TimeoutError:
        return ExtractionResult(error="timeout")
    except OSError:
        return ExtractionResult(error="timeout")
    except _NotFoundError:
        return ExtractionResult(error="not_found")
    except _HttpStatusError:
        return ExtractionResult(error="api_error")

    # Name falls back from og:title to <title>, then to empty — never to the URL.
    # An empty name signals "no title found" so the create form leaves Page Name
    # blank (and focused) for the user to fill, rather than prefilling a URL that
    # reads as a junk title.
    name = meta.og_title or meta.title or ""
    draft = ExtractionDraft(
        name=name,
        source_type="web",
        author="",
        publisher=meta.og_site_name or "",
        url=url,
    )
    result = ExtractionResult(draft=draft, confidence="low", source_api="og_meta")

    # 4. Cache it
    cache.set(cache_key, result, _CACHE_TTL)

    return result
