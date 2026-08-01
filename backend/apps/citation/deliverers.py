"""Declared deliverer hosts — stores and streaming platforms that serve copies.

A **deliverer** hosts copies of works whose identity lives elsewhere: an
``amazon.com/dp/…`` URL is the copy consulted (a future access URL), not the
identity of a work, so recognizing it as a web page would *fabricate
identity* — minting an "Amazon page" child when the evidence is the book or
movie the URL merely delivers.

This is the fourth recognizer's host table arriving early: a separate
declared table, sibling to the scheme registry and ``CitationSourceRootDomain``
— deliberately neither (a scheme match mints identity; a deliverer match
forbids it). It copies the scheme framework's authoring discipline: entries
are pure configuration, malformed declarations fail at import, and matching
reuses ``hosts.py``'s label-boundary suffix vocabulary so deliverer hosts and
recognition hosts stay one language.

Consumers: ``extractors.classify_url`` (the classification every interactive
surface switches on), ``url_extraction.extract_url`` (the ISBN auto-classify
path and the teaching notice), and ``CitationSourceRootDomain.clean()`` (a
deliverer host can never become a recognition domain). The patch path needs
no guard — it already refuses to mint parentless web roots.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse

from apps.citation.citation_types import CitationSourceTypeValue, SourceType
from apps.citation.hosts import Host, is_dns_host, label_suffixes, normalize_host
from apps.citation.isbn import isbn_checksum_ok, normalize_isbn


class KindPathHint(NamedTuple):
    """A path shape that narrows a mixed storefront's work kind.

    Wording/preselect only — a kind hint never changes the classification
    outcome (the tunes-message-never-outcome invariant). ``pattern`` is a
    regex source searched against the URL *path*; ``kind`` is the citation
    type key it suggests (open vocabulary, validated at import).
    """

    pattern: str
    kind: CitationSourceTypeValue


@dataclass(frozen=True, slots=True)
class DelivererSpec:
    """One deliverer's declared facts. Pure configuration — no behavior.

    - ``label``: user-facing platform name ("Amazon", "Netflix"), used in
      every message.
    - ``hosts``: normalized hosts the platform owns, matched by
      label-boundary suffix (``smile.amazon.de`` matches ``amazon.de``;
      lookalike ``notamazon.com`` never does). Enumerated — no wildcards.
    - ``delivers``: the single work kind served (a citation type key —
      deliberately open vocabulary, not a closed book/video pair), or
      ``None`` when mixed (Amazon). Drives message wording and the create
      form's preselected type.
    - ``isbn_path_patterns`` / ``isbn_query_params``: where a work's ISBN
      rides in the platform's URLs, when it does. Declarations say *where to
      look*; shape + checksum validation happens in :func:`embedded_isbn`,
      so a coincidental ten-character token can't trigger a bogus lookup.
    - ``kind_path_patterns``: the mixed-storefront work-kind hints.
    - ``works_phrase``: optional message-noun override for a platform whose
      default noun would be wrong (Audible's "audiobook editions of books").
      Wording only.
    """

    label: str
    hosts: tuple[str, ...]
    delivers: CitationSourceTypeValue | None = None
    isbn_path_patterns: tuple[str, ...] = ()
    isbn_query_params: tuple[str, ...] = ()
    kind_path_patterns: tuple[KindPathHint, ...] = ()
    works_phrase: str = ""


# Amazon product pages: ``/dp/<ASIN>``, ``/<title-slug>/dp/<ASIN>``,
# ``/gp/product/<ASIN>``, mobile ``/gp/aw/d/<ASIN>`` and the ancient
# ``/exec/obidos/ASIN/<ASIN>``. Only an ISBN-10-shaped ASIN is captured —
# Kindle/e-book/media ASINs start with a letter (``B0…``) and never match.
_AMAZON_ISBN_PATH = (
    r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/(?P<isbn>\d{9}[\dXx])(?=/|$)"
)

DELIVERERS: tuple[DelivererSpec, ...] = (
    DelivererSpec(
        label="Amazon",
        hosts=(
            "amazon.com",
            "amazon.ca",
            "amazon.com.mx",
            "amazon.com.br",
            "amazon.co.uk",
            "amazon.de",
            "amazon.fr",
            "amazon.it",
            "amazon.es",
            "amazon.nl",
            "amazon.se",
            "amazon.pl",
            "amazon.com.tr",
            "amazon.ae",
            "amazon.sa",
            "amazon.eg",
            "amazon.in",
            "amazon.sg",
            "amazon.co.jp",
            "amazon.cn",
            "amazon.com.au",
            # Opaque short-link hosts: no path to extract from, so they land
            # on the mixed notice — but without them a short link would mint
            # an "a.co" site. aws.amazon.com is a known, accepted false
            # positive of the suffix match (see the plan's survey).
            "a.co",
            "amzn.to",
            "amzn.eu",
            "amzn.asia",
        ),
        delivers=None,  # books, movies and everything else
        isbn_path_patterns=(_AMAZON_ISBN_PATH,),
        kind_path_patterns=(KindPathHint(r"/gp/video/", "video"),),
    ),
    DelivererSpec(
        label="Audible",
        hosts=(
            "audible.com",
            "audible.ca",
            "audible.co.uk",
            "audible.com.au",
            "audible.de",
            "audible.fr",
            "audible.it",
            "audible.es",
            "audible.in",
            "audible.co.jp",
        ),
        delivers="book",
        # /pd/<slug>/<ASIN> ASINs are B0…, never ISBNs — notice only. An
        # audiobook is a manifestation of the book; the work cited is the book.
        works_phrase="audiobook editions of books",
    ),
    DelivererSpec(
        label="Barnes & Noble",
        hosts=("barnesandnoble.com", "bn.com"),
        delivers="book",
        isbn_query_params=("ean",),
    ),
    DelivererSpec(
        label="AbeBooks",
        hosts=(
            "abebooks.com",
            "abebooks.co.uk",
            "abebooks.de",
            "abebooks.fr",
            "abebooks.it",
        ),
        delivers="book",
        isbn_query_params=("isbn",),
        isbn_path_patterns=(r"^/(?P<isbn>97[89]\d{10})(?=/|$)",),
    ),
    DelivererSpec(label="Apple TV", hosts=("tv.apple.com",), delivers="video"),
    # /<region>/book/… and /<region>/audiobook/… are both books; Apple store
    # ids aren't ISBNs, so no extraction.
    DelivererSpec(label="Apple Books", hosts=("books.apple.com",), delivers="book"),
    # Legacy mixed storefront (music, video, books).
    DelivererSpec(label="iTunes", hosts=("itunes.apple.com",), delivers=None),
    DelivererSpec(label="Prime Video", hosts=("primevideo.com",), delivers="video"),
    DelivererSpec(label="Netflix", hosts=("netflix.com",), delivers="video"),
    DelivererSpec(label="HBO Max", hosts=("hbomax.com", "max.com"), delivers="video"),
    DelivererSpec(label="Disney+", hosts=("disneyplus.com",), delivers="video"),
    DelivererSpec(label="Hulu", hosts=("hulu.com",), delivers="video"),
    DelivererSpec(label="Paramount+", hosts=("paramountplus.com",), delivers="video"),
    DelivererSpec(label="Peacock", hosts=("peacocktv.com",), delivers="video"),
    DelivererSpec(label="Tubi", hosts=("tubitv.com",), delivers="video"),
    DelivererSpec(
        label="Google Play",
        hosts=("play.google.com",),
        delivers=None,
        kind_path_patterns=(
            KindPathHint(r"^/store/books/", "book"),
            KindPathHint(r"^/store/audiobooks/", "book"),
            KindPathHint(r"^/store/movies/", "video"),
        ),
    ),
    # Known miss, accepted: new-style google.com/books/edition/… lives on
    # google.com, which cannot be host-blocked. Rare; F5 gardening catches it.
    DelivererSpec(label="Google Books", hosts=("books.google.com",), delivers="book"),
)


def _validate_and_index(
    specs: tuple[DelivererSpec, ...],
) -> dict[Host, DelivererSpec]:
    """Index *specs* by host, validating every declaration at import.

    The scheme framework's fail-at-registration rule: an un-normalized or
    non-DNS host, a host claimed twice, nested hosts (which would make
    match order matter), an invalid ``delivers``/kind key, or a malformed
    pattern all fail the import, not the first paste.
    """
    index: dict[Host, DelivererSpec] = {}
    for spec in specs:
        kinds = [hint.kind for hint in spec.kind_path_patterns]
        if spec.delivers is not None:
            kinds.append(spec.delivers)
        for kind in kinds:
            if kind not in SourceType.values:
                raise ValueError(
                    f"Deliverer {spec.label!r} declares unknown work kind {kind!r}."
                )
        for pattern in spec.isbn_path_patterns:
            if "(?P<isbn>" not in pattern:
                raise ValueError(
                    f"Deliverer {spec.label!r} ISBN pattern {pattern!r} lacks "
                    f"an (?P<isbn>…) group."
                )
            re.compile(pattern)
        for hint in spec.kind_path_patterns:
            re.compile(hint.pattern)
        for raw in spec.hosts:
            host = Host(raw)
            if normalize_host(raw) != raw or not is_dns_host(host):
                raise ValueError(
                    f"Deliverer {spec.label!r} declares invalid host {raw!r}: "
                    f"hosts must be normalized DNS names."
                )
            if host in index:
                raise ValueError(
                    f"Deliverer host {raw!r} declared twice "
                    f"({index[host].label!r} and {spec.label!r})."
                )
            index[host] = spec
    # No declared host may nest under another — suffix matching would then
    # depend on evaluation order.
    for host in index:
        for suffix in label_suffixes(host)[1:]:
            if suffix in index:
                raise ValueError(
                    f"Deliverer host {host!r} nests under declared host "
                    f"{suffix!r}; declare only the outer host."
                )
    return index


_BY_HOST: dict[Host, DelivererSpec] = _validate_and_index(DELIVERERS)


def deliverer_for_host(host: Host) -> DelivererSpec | None:
    """The deliverer owning *host*, by label-boundary suffix, or ``None``."""
    for suffix in label_suffixes(host):
        spec = _BY_HOST.get(suffix)
        if spec is not None:
            return spec
    return None


def deliverer_for_url(url: str) -> DelivererSpec | None:
    """The deliverer owning *url*'s host, or ``None``.

    Abstains (like recognition) on a URL whose host is missing, unparseable
    or not a syntactic DNS name.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    host = normalize_host(parsed.hostname)
    if not is_dns_host(host):
        return None
    return deliverer_for_host(host)


def embedded_isbn(url: str, spec: DelivererSpec) -> str | None:
    """The work ISBN *url* embeds per *spec*'s declared shapes, or ``None``.

    Interpretation side of the declarations: every candidate — a path-pattern
    ``isbn`` group or a declared query param's value — is normalized and
    **checksum-gated**, so a coincidental digit run (a non-book ASIN, a junk
    ``ean=``) falls through to the notice rather than triggering a bogus
    Open Library lookup. First valid candidate wins; paths before params,
    declaration order within each.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    for pattern in spec.isbn_path_patterns:
        match = re.search(pattern, parsed.path)
        if match is None:
            continue
        isbn = normalize_isbn(match.group("isbn"))
        if isbn is not None and isbn_checksum_ok(isbn):
            return isbn
    if spec.isbn_query_params:
        params = parse_qs(parsed.query)
        for param in spec.isbn_query_params:
            for value in params.get(param, []):
                isbn = normalize_isbn(value)
                if isbn is not None and isbn_checksum_ok(isbn):
                    return isbn
    return None


def suggested_work_kind(
    url: str, spec: DelivererSpec
) -> CitationSourceTypeValue | None:
    """The work kind to suggest for *url*: a path hint, else the spec default.

    Wording/preselect only — never the outcome (the invariant).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return spec.delivers
    for hint in spec.kind_path_patterns:
        if re.search(hint.pattern, parsed.path):
            return hint.kind
    return spec.delivers


# Message fragments per suggested kind. A kind outside the table (a future
# type) gets a generic derivation until its real template arrives with the
# type — see the plan's podcast stress test.
_NOUN_BY_KIND = {
    "book": "copies of books",
    "video": "copies of movies and shows",
}
_TARGET_BY_KIND = {
    "book": "the book itself",
    "video": "the movie or video itself",
}
_MIXED_NOUN = "copies of works"
_MIXED_TARGET = "the work itself (the book, movie or other work)"


def deliverer_notice_message(
    spec: DelivererSpec, kind: CitationSourceTypeValue | None
) -> str:
    """The teaching-notice / 422 message for *spec* at suggested *kind*.

    One composition rule for every surface (extract notice, ``cite-url`` and
    ``pages/`` 422s), so the guardrail reads identically everywhere.
    """
    if kind is None:
        noun, target = _MIXED_NOUN, _MIXED_TARGET
    else:
        noun = _NOUN_BY_KIND.get(kind, f"copies of {kind} works")
        target = _TARGET_BY_KIND.get(kind, f"the {kind} itself")
    if spec.works_phrase:
        noun = spec.works_phrase
    return f"{spec.label} delivers {noun} — cite {target}, not the {spec.label} page."
