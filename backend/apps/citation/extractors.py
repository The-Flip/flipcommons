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
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.db import transaction

from apps.citation.hosts import normalize_host
from apps.citation.models import (
    CITATION_SOURCE_NAME_MAX_LENGTH,
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)

if TYPE_CHECKING:
    from apps.accounts.models import User


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
            CitationSource.objects.filter(identifier_key=key)
            .roots()
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

    # --- Step 3: Recognition-host match (exact host) -----------------------
    # SUBDOMAIN-MATCHING-DISABLED (re-enabled in DomainGovernance G3): match the
    # normalized host exactly, not by longest label-boundary suffix. Exact
    # matching can't over-match, so it ships with no public-suffix guard; the
    # label_suffixes/longest_suffix_match helpers stay built and tested in
    # hosts.py, dormant, until G3 re-points this step at them.
    parsed = urlparse(url)
    if not parsed.hostname:
        return None

    host = normalize_host(parsed.hostname)

    # The root-only filter is defense-in-depth for the app-level clean()
    # invariant (rows inserted via raw SQL / bulk that bypass it).
    row = (
        CitationSourceRootDomain.objects.filter(
            host=host,
            source__parent__isnull=True,
        )
        .values_list("source_id", "source__name")
        .first()
    )
    if row is None:
        return None
    source_id, source_name = row
    return Recognition(parent_id=source_id, parent_name=source_name)


def web_child_name(url: str, name: str = "") -> str:
    """Pick a display name for a web child source.

    Prefers a caller-supplied *name* (a reviewed page name), else the *url*
    itself; when that candidate exceeds the name-column limit, falls back to the
    URL's hostname (or a truncated URL when even the hostname is missing). A
    non-empty *url* yields a non-blank result.
    """
    candidate = name or url
    if len(candidate) <= CITATION_SOURCE_NAME_MAX_LENGTH:
        return candidate
    return urlparse(url).hostname or url[:CITATION_SOURCE_NAME_MAX_LENGTH]


def create_web_child(
    parent_id: int,
    url: str,
    name: str = "",
    *,
    created_by: User | None = None,
) -> CitationSource:
    """Mint a validated web-page child under *parent_id*, linked at *url*.

    The child and its ``reference`` link are both ``full_clean``d, so a
    malformed *url* is rejected by the ``URLField`` format check rather than
    silently stored. The display name follows the ``web_child_name`` rule.

    ``created_by`` attributes both rows; ``None`` leaves ``created_by`` /
    ``updated_by`` null. Raises ``ValidationError`` on invalid input. Atomic, so
    a link that fails validation leaves no orphaned child behind.
    """
    with transaction.atomic():
        child = CitationSource(
            name=web_child_name(url, name),
            source_type=CitationSource.SourceType.WEB,
            parent_id=parent_id,
            created_by=created_by,
            updated_by=created_by,
        )
        child.full_clean()
        child.save()
        link = CitationSourceLink(
            citation_source=child,
            link_type=CitationSourceLink.LinkType.REFERENCE,
            url=url,
            created_by=created_by,
            updated_by=created_by,
        )
        link.full_clean()
        link.save()
    return child


def get_or_create_scheme_child(
    root: CitationSource,
    identifier: str,
    *,
    created_by: User | None = None,
) -> CitationSource:
    """Get-or-create the ``(root, identifier)`` scheme child under *root*.

    *identifier* is normalized through the root's extractor, so a raw URL and a
    bare id resolve to the same child. Idempotent — re-citing an identifier
    reuses its child. The child carries the ``{root.name} #{id}`` name and a
    canonical ``reference`` link, ``full_clean``d on first create.

    ``created_by`` attributes the child; ``None`` leaves it null. Raises
    ``ValueError`` if *root* carries no known ``identifier_key`` scheme or the
    identifier is invalid for it.
    """
    extractor = EXTRACTORS.get(root.identifier_key)
    if extractor is None:
        raise ValueError(
            f"Root source {root.pk} has no known identifier scheme "
            f"({root.identifier_key!r})"
        )
    normalized = extractor.normalize(identifier)
    if normalized is None:
        raise ValueError(f"Invalid {root.identifier_key} identifier {identifier!r}")

    # Field-validate the candidate (the id regex has no length cap, so a too-long
    # identifier or generated name must surface as a ValidationError, not a DB
    # error). Skip unique + constraint validation: the (root, identifier) dedup
    # is get_or_create's job — re-citing must reuse, not raise on the unique
    # constraint — and the DB enforces the rest on save. Atomic so the child and
    # its link land together or not at all.
    with transaction.atomic():
        candidate = CitationSource(
            name=f"{root.name} #{normalized}",
            source_type=CitationSource.SourceType.WEB,
            parent=root,
            identifier=normalized,
            created_by=created_by,
            updated_by=created_by,
        )
        candidate.full_clean(validate_unique=False, validate_constraints=False)
        source, created = CitationSource.objects.get_or_create(
            parent=root,
            identifier=normalized,
            defaults={
                "name": candidate.name,
                "source_type": candidate.source_type,
                "created_by": created_by,
                "updated_by": created_by,
            },
        )
        if created:
            link = CitationSourceLink(
                citation_source=source,
                link_type=CitationSourceLink.LinkType.REFERENCE,
                url=extractor.build_url(normalized),
                created_by=created_by,
                updated_by=created_by,
            )
            link.full_clean()
            link.save()
    return source


def get_or_create_external_source(scheme: str, identifier: str) -> CitationSource:
    """Get-or-create the child ``CitationSource`` for ``scheme:identifier``.

    Resolves the root source owning *scheme* (e.g. the IPDB root), then
    get-or-creates the ``(root, identifier)`` child under it via
    ``get_or_create_scheme_child``.

    Raises ``CitationSource.DoesNotExist`` if no root for *scheme* is seeded,
    and ``ValueError`` if the scheme or identifier is invalid.
    """
    if scheme not in EXTRACTORS:
        raise ValueError(f"Unknown citation scheme {scheme!r}")

    root = (
        CitationSource.objects.filter(identifier_key=scheme)
        .roots()
        .only("id", "name", "identifier_key")
        .first()
    )
    if root is None:
        raise CitationSource.DoesNotExist(
            f"No root CitationSource seeded for scheme {scheme!r}; "
            f"seed citation sources before applying a patch that cites it."
        )
    return get_or_create_scheme_child(root, identifier)


def get_or_create_web_source(url: str, archive_url: str = "") -> CitationSource:
    """Get-or-create the web ``CitationSource`` a raw ``url`` cites.

    When ``archive_url`` is given (e.g. a Wayback permalink), it is additively
    attached as a second ``archive``-typed link on the resolved source, so one
    citation carries both the live page and its durable snapshot. The
    attachment is idempotent (get-or-create by ``(source, url)``), so a
    re-applied patch never duplicates it, and a no-op when ``archive_url`` is
    empty or equal to ``url``.

    For citing a web page (forum post, archive scan, manufacturer page) that no
    extractor scheme covers. Routes through ``recognize_url`` so the URL
    resolves to a *known* source:

    * an existing *child* that already covers the URL (exact link or scheme
      identifier) is reused;
    * a domain match to a seeded root (e.g. the "Kineticist" source) becomes a
      new child *under that root* — including when the URL equals the root's own
      homepage link, since a root is abstract and never directly citable.

    A URL whose domain matches no seeded root raises
    ``CitationSource.DoesNotExist`` (mirroring the scheme path's missing-root
    error). We deliberately do *not* mint a parentless web source: a root web
    source is *abstract* — a container, not directly-citable evidence (see
    ``CitationSource.is_abstract``) — so a parentless page
    would be concrete in intent but root-like in citation search/UI. Seed the
    website root in an earlier patch, then cite pages under it.

    A newly minted child's link is typed ``reference`` — it's an evidence page,
    not a root's homepage. Recognition keys off ``CitationSourceRootDomain``, so
    ``link_type`` is display convention.

    Idempotent by exact URL — re-citing the same URL (or citing one a curator
    already linked to a child) reuses the existing source, so a re-applied patch
    never duplicates. Only *child* links count for reuse; a root's homepage link
    is ignored so the cite resolves to a page under the root, not the root.

    The caller is responsible for rejecting URLs that match a known scheme;
    those must be cited as ``scheme:identifier`` so they dedup through the
    scheme path.
    """
    with transaction.atomic():
        # Children only: a root's own homepage link can equal the cited URL, but
        # a root is abstract — reusing it would cite the container, not a page.
        # Filter to child links so the cite falls through to a domain match that
        # mints a child (recognize_url's own exact-link step is children-only).
        existing = (
            CitationSourceLink.objects.filter(
                url=url, citation_source__parent__isnull=False
            )
            .select_related("citation_source")
            .first()
        )
        if existing is not None:
            source = existing.citation_source
        else:
            recognition = recognize_url(url)
            if recognition is None:
                raise CitationSource.DoesNotExist(
                    f"No website CitationSource root's recognition domain matches "
                    f"{url!r}; declare the root in a patch — a sources: root's "
                    f"homepage host is minted as its recognition domain — before "
                    f"citing a page under it."
                )
            if recognition.child is not None:
                source = CitationSource.objects.get(pk=recognition.child.id)
            else:
                # Domain match: mint a new validated child under the recognized
                # root, unattributed (created_by stays null).
                source = create_web_child(recognition.parent_id, url)

        # The durable snapshot (Wayback/archive.today) rides as a second,
        # validated link — not domain-matched, it intentionally lives on a
        # different host than the page it preserves. Idempotent by URL.
        wants_archive = bool(archive_url) and archive_url != url
        if (
            wants_archive
            and not CitationSourceLink.objects.filter(
                citation_source=source, url=archive_url
            ).exists()
        ):
            archive = CitationSourceLink(
                citation_source=source,
                url=archive_url,
                link_type=CitationSourceLink.LinkType.ARCHIVE,
            )
            archive.full_clean()
            archive.save()
    return source
