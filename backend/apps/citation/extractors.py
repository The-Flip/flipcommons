"""Backend extractor registry for citation source URL recognition.

Each extractor is keyed by an ``identifier_key`` value and knows how to
parse a URL into a structured identifier and build a canonical URL from
an identifier.

The ``recognize_url`` function is the main entry point: given a raw URL
it tries extractors first, then checks for an exact child-link match,
then falls back to domain matching against homepage links.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from apps.citation.models import CitationSource, CitationSourceLink


@dataclass(frozen=True)
class Extractor:
    """Knows how to parse and build URLs for one identifier scheme."""

    source_name: str
    url_pattern: re.Pattern[str]
    id_pattern: re.Pattern[str]
    build_url: Callable[[str], str]

    def extract(self, url: str) -> str | None:
        """Return the identifier from *url*, or ``None``."""
        m = self.url_pattern.search(url)
        return m.group(1) if m else None

    def normalize(self, raw: str) -> str | None:
        """Extract a valid identifier from a URL or bare value, or ``None``.

        Tries the URL pattern first, then validates as a bare identifier.
        """
        m = self.url_pattern.search(raw)
        if m:
            return m.group(1)
        return raw if self.id_pattern.fullmatch(raw) else None


EXTRACTORS: dict[str, Extractor] = {
    "ipdb": Extractor(
        source_name="IPDB",
        url_pattern=re.compile(r"https?://(?:www\.)?ipdb\.org/machine\.cgi\?id=(\d+)"),
        id_pattern=re.compile(r"\d+"),
        build_url=lambda id: f"https://www.ipdb.org/machine.cgi?id={id}",
    ),
    "opdb": Extractor(
        source_name="OPDB",
        url_pattern=re.compile(
            r"https?://(?:www\.)?opdb\.org/machines/([A-Za-z0-9_-]+)"
        ),
        id_pattern=re.compile(r"[A-Za-z0-9_-]+"),
        build_url=lambda id: f"https://opdb.org/machines/{id}",
    ),
}


@dataclass
class RecognitionChild:
    """Child-source portion of a :class:`Recognition`.

    Grouping ``id`` / ``name`` / ``skip_locator`` here encodes the runtime
    invariant that they're either all present or all absent — callers can
    narrow with ``if rec.child is not None`` and access fields without
    per-field ``None`` checks.
    """

    id: int
    name: str
    skip_locator: bool = False


@dataclass
class Recognition:
    """Result of recognizing a pasted URL."""

    parent_id: int
    parent_name: str
    child: RecognitionChild | None = None
    identifier: str | None = None


def _normalize_domain(hostname: str) -> str:
    """Strip ``www.`` prefix for domain comparison."""
    return hostname.removeprefix("www.").lower()


def recognize_url(url: str) -> Recognition | None:
    """Try to recognize a pasted URL against known sources.

    Three-step resolution:

    1. Try all extractors — can identify parent + extract identifier,
       then look up existing child by identifier.
    2. Check if the full URL exactly matches any child source's linked
       URL — returns parent + child for instant re-citation.
    3. Fall back to domain matching against ``link_type="homepage"``
       links — returns parent only, no identifier.

    Domain matching normalises away ``www.`` but compares full
    subdomains (``twip.kineticist.com`` ≠ ``kineticist.com``).
    """
    # --- Step 1: Extractor match -------------------------------------------
    for key, extractor in EXTRACTORS.items():
        extracted_id = extractor.extract(url)
        if extracted_id is None:
            continue

        # Find the parent source that uses this extractor.
        parent = (
            CitationSource.objects.filter(identifier_key=key, parent__isnull=True)
            .only("id", "name")
            .first()
        )
        if parent is None:
            continue

        # Look for an existing child with this identifier.
        child = (
            CitationSource.objects.filter(parent=parent, identifier=extracted_id)
            .only("id", "name", "source_type", "parent_id")
            .first()
        )
        if child:
            return Recognition(
                parent_id=parent.id,
                parent_name=parent.name,
                child=RecognitionChild(
                    id=child.id,
                    name=child.name,
                    skip_locator=child.skip_locator,
                ),
                identifier=extracted_id,
            )
        return Recognition(
            parent_id=parent.id,
            parent_name=parent.name,
            identifier=extracted_id,
        )

    # --- Step 2: Full URL child-link match ---------------------------------
    child_link = (
        CitationSourceLink.objects.filter(
            url=url, citation_source__parent__isnull=False
        )
        .select_related("citation_source", "citation_source__parent")
        .first()
    )
    if child_link:
        child = child_link.citation_source
        parent = child.parent
        if parent is None:
            return None
        return Recognition(
            parent_id=parent.pk,
            parent_name=parent.name,
            child=RecognitionChild(
                id=child.pk,
                name=child.name,
                skip_locator=child.skip_locator,
            ),
        )

    # --- Step 3: Domain match against homepage links -----------------------
    parsed = urlparse(url)
    if not parsed.hostname:
        return None

    input_domain = _normalize_domain(parsed.hostname)

    # Query homepage links and compare domains in Python (small result set).
    homepage_links = CitationSourceLink.objects.filter(
        link_type="homepage",
        citation_source__parent__isnull=True,
    ).values_list("citation_source_id", "citation_source__name", "url")

    for source_id, source_name, homepage_url in homepage_links:
        hp_parsed = urlparse(homepage_url)
        if hp_parsed.hostname and _normalize_domain(hp_parsed.hostname) == input_domain:
            return Recognition(parent_id=source_id, parent_name=source_name)

    return None


def get_or_create_external_source(scheme: str, identifier: str) -> CitationSource:
    """Get-or-create the child ``CitationSource`` for ``scheme:identifier``.

    Looks up the root source for ``scheme`` (e.g. the IPDB root), then
    get-or-creates the ``(parent=root, identifier)`` child, attaching a
    homepage link with the canonical URL on first creation.

    Idempotent by design — re-citing the same id reuses the existing child.
    This differs from ``api.create_citation_source``, which plain-creates and
    422s on a duplicate: a re-applied data patch must not error, so the
    new-idempotency semantics live here rather than in that endpoint.

    Raises ``CitationSource.DoesNotExist`` if the root for ``scheme`` isn't
    seeded, and ``ValueError`` if the scheme/identifier is invalid.
    """
    extractor = EXTRACTORS.get(scheme)
    if extractor is None:
        raise ValueError(f"Unknown citation scheme {scheme!r}")
    normalized = extractor.normalize(identifier)
    if normalized is None:
        raise ValueError(f"Invalid {scheme} identifier {identifier!r}")

    root = (
        CitationSource.objects.filter(identifier_key=scheme, parent__isnull=True)
        .only("id", "name")
        .first()
    )
    if root is None:
        raise CitationSource.DoesNotExist(
            f"No root CitationSource seeded for scheme {scheme!r}; "
            f"seed citation sources before applying a patch that cites it."
        )

    source, created = CitationSource.objects.get_or_create(
        parent=root,
        identifier=normalized,
        defaults={
            "name": f"{root.name} #{normalized}",
            "source_type": CitationSource.SourceType.WEB,
        },
    )
    if created:
        CitationSourceLink.objects.create(
            citation_source=source,
            link_type=CitationSourceLink.LinkType.HOMEPAGE,
            url=extractor.build_url(normalized),
        )
    return source
