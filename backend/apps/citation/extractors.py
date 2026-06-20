"""Backend extractor registry for citation source URL recognition.

Each extractor is keyed by an ``identifier_key`` value and knows how to
parse a URL into a structured identifier and build a canonical URL from
an identifier.

The ``recognize_url`` function is the main entry point: given a raw URL
it tries extractors first, then checks for an exact child-link match,
then falls back to recognition-host matching via ``CitationSourceRootDomain``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from apps.citation.hosts import (
    RootDomainMatch,
    label_suffixes,
    longest_suffix_match,
    normalize_host,
)
from apps.citation.models import (
    CITATION_SOURCE_NAME_MAX_LENGTH,
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)


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
    "youtube": Extractor(
        source_name="YouTube",
        # YouTube's one 11-char video id, reached through any URL shape
        # (watch?v=, youtu.be/, /shorts/, /embed/, /live/, mobile `m.`) plus
        # trailing params — all collapse to one canonical child. Host-bound on
        # `https?://<host>` like the others so `notyoutube.com` can't match, and
        # `(?![A-Za-z0-9_-])` pins the id to 11 chars so a 12-char typo fails
        # instead of truncating to a wrong-but-valid-looking id.
        url_pattern=re.compile(
            r"https?://(?:"
            r"(?:www\.|m\.)?youtube\.com/(?:watch\?(?:[^\s]*&)?v=|embed/|shorts/|live/)"
            r"|(?:www\.)?youtu\.be/"
            r")([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
        ),
        id_pattern=re.compile(r"[A-Za-z0-9_-]{11}"),
        build_url=lambda id: f"https://www.youtube.com/watch?v={id}",
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


def recognize_url(url: str) -> Recognition | None:
    """Try to recognize a pasted URL against known sources.

    Three-step resolution:

    1. Try all extractors — identify the scheme parent + extract its
       identifier, then look up an existing child by that identifier.
    2. Check if the full URL exactly matches a child source's linked
       URL — returns parent + child for instant re-citation.
    3. Fall back to recognition-host matching: resolve the URL's host to
       the root that owns it via ``CitationSourceRootDomain``, longest
       label-boundary suffix wins — returns parent only, no identifier.

    Step 3 matches subdomains most-specific-first: an asset host
    ``s4.american-pinball.com`` collapses to the ``american-pinball.com``
    root, while a deliberately-seeded ``twip.kineticist.com`` still wins
    over ``kineticist.com`` for its own subtree. The recognition host is
    an owned fact on the root (``CitationSourceRootDomain``), decoupled
    from the display ``homepage`` link — declared deliberately, never
    inferred and never via external HTTP. See ``docs/Citations.md``.
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

    # --- Step 3: Recognition-host match (longest label-boundary suffix) -----
    parsed = urlparse(url)
    if not parsed.hostname:
        return None

    host = normalize_host(parsed.hostname)

    # Only suffixes of the input host can match, so the DB filters to those; the
    # root-only filter is defense-in-depth for the app-level clean() invariant
    # (rows inserted via raw SQL / bulk that bypass it).
    rows = CitationSourceRootDomain.objects.filter(
        host__in=label_suffixes(host),
        source__parent__isnull=True,
    ).values_list("source_id", "source__name", "host")
    candidates = [
        RootDomainMatch(source_id, source_name, candidate_host)
        for source_id, source_name, candidate_host in rows
    ]
    winner = longest_suffix_match(host, candidates)
    if winner is None:
        return None
    return Recognition(parent_id=winner.source_id, parent_name=winner.source_name)


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
        # A record page is a child under the scheme root, so its link is
        # ``reference``; ``homepage`` is conventionally a root's own page.
        # ``link_type`` no longer affects recognition (that keys off
        # ``CitationSourceRootDomain``) — this is display convention.
        CitationSourceLink.objects.create(
            citation_source=source,
            link_type=CitationSourceLink.LinkType.REFERENCE,
            url=extractor.build_url(normalized),
        )
    return source


def get_or_create_web_source(url: str, archive_url: str = "") -> CitationSource:
    """Get-or-create the web ``CitationSource`` a raw ``url`` cites.

    When ``archive_url`` is given (e.g. a Wayback permalink), it is additively
    attached as a second ``archive``-typed link on the resolved source, so one
    citation carries both the live page and its durable snapshot. The
    attachment is idempotent (get-or-create by ``(source, url)``), so a
    re-applied patch never duplicates it, and a no-op when ``archive_url`` is
    empty or equal to ``url``.

    For citing a web page (forum post, archive scan, manufacturer page) that no
    extractor scheme covers. Routes through ``recognize_url`` — the same
    recognition the interactive editor uses — so the URL resolves to a *known*
    source:

    * an existing child that already covers the URL (exact link or scheme
      identifier) is reused;
    * a domain match to a seeded root (e.g. the "Kineticist" source) becomes a
      new child *under that root*.

    A URL whose domain matches no seeded root raises
    ``CitationSource.DoesNotExist`` (mirroring the scheme path's missing-root
    error). We deliberately do *not* mint a parentless web source: a root web
    source is *abstract* — a container, not directly-citable evidence (see
    ``apps.citation.schemas`` / ``api._is_abstract``) — so a parentless page
    would be concrete in intent but root-like in citation search/UI. Seed the
    website root in an earlier patch, then cite pages under it.

    A newly minted child's link is typed ``reference`` — it's an evidence page,
    not a root's homepage. ``link_type`` no longer affects recognition (that
    keys off ``CitationSourceRootDomain``), so this is display convention.

    Idempotent by exact URL — re-citing the same URL (or citing one a curator
    already linked) reuses the existing source, so a re-applied patch never
    duplicates.

    The caller is responsible for rejecting URLs that match a known scheme;
    those must be cited as ``scheme:identifier`` so they dedup through the
    scheme path.
    """
    existing = (
        CitationSourceLink.objects.filter(url=url)
        .select_related("citation_source")
        .first()
    )
    if existing is not None:
        source = existing.citation_source
    else:
        recognition = recognize_url(url)
        if recognition is None:
            raise CitationSource.DoesNotExist(
                f"No website CitationSource root matches {url!r}; seed the website "
                f"root (a parentless source whose homepage link shares the domain) "
                f"before citing a page under it."
            )
        if recognition.child is not None:
            source = CitationSource.objects.get(pk=recognition.child.id)
        else:
            # Domain match: a new child under the recognized root. Name defaults
            # to the URL; the link column allows more than the name column, so
            # fall back to the hostname for an over-long URL.
            name = url
            if len(name) > CITATION_SOURCE_NAME_MAX_LENGTH:
                name = urlparse(url).hostname or url[:CITATION_SOURCE_NAME_MAX_LENGTH]

            source = CitationSource.objects.create(
                name=name,
                source_type=CitationSource.SourceType.WEB,
                parent_id=recognition.parent_id,
            )
            CitationSourceLink.objects.create(
                citation_source=source,
                link_type=CitationSourceLink.LinkType.REFERENCE,
                url=url,
            )

    if archive_url and archive_url != url:
        # The durable snapshot (Wayback/archive.today) rides as a second link on
        # the same source. Not domain-matched to a root — it intentionally lives
        # on a different host than the page it preserves.
        CitationSourceLink.objects.get_or_create(
            citation_source=source,
            url=archive_url,
            defaults={"link_type": CitationSourceLink.LinkType.ARCHIVE},
        )
    return source
