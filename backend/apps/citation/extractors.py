"""Citation source URL recognition and get-or-create write helpers.

The ``recognize_url`` function is the main entry point: given a raw URL
it tries the registered identifier schemes first, then checks for an exact
child-link match, then falls back to recognition-host matching via
``CitationSourceRootDomain``.

The schemes themselves (URL patterns, id grammars, canonical URLs) are
plugins — see ``apps.citation.citation_types``. This module is the core
consumer: it owns every DB touch (lookups, child minting) so scheme specs
stay pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.db import transaction

from apps.citation.citation_types import (
    SCHEME_DRIVERS,
    CitationSourceTypeValue,
    citation_source_type,
    citation_type_driver,
    is_known_scheme,
    known_scheme_keys,
    recognize_scheme,
    scheme_start_seconds_hint,
)
from apps.citation.deliverers import (
    DelivererSpec,
    deliverer_for_url,
    embedded_isbn,
    suggested_work_kind,
)
from apps.citation.hosts import (
    Host,
    PathPrefix,
    RootDomainMatch,
    is_dns_host,
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
from apps.citation.shared_hosts import shared_host_for
from apps.core.types import CitationSourceId

if TYPE_CHECKING:
    from collections.abc import Callable

    from apps.actors.models import Actor


@dataclass
class RecognitionChild:
    """Child-source portion of a :class:`Recognition`.

    Grouping ``id`` / ``name`` / ``source_type`` / ``skip_locator`` here
    encodes the runtime invariant that they're either all present or all
    absent — callers can narrow with ``if rec.child is not None`` and access
    fields without per-field ``None`` checks. ``source_type`` is the typed
    Literal, coerced from the model's raw field at construction, so consumers
    read a validated value rather than a bare ``str``.
    """

    id: CitationSourceId
    name: str
    source_type: CitationSourceTypeValue
    skip_locator: bool = False


@dataclass
class Recognition:
    """Result of recognizing a pasted URL.

    ``locator_hint`` prefills the cite flow's locator stage: a pasted video
    URL carrying a start time (``?t=95``) yields the canonical locator text
    (``"1:35"``), formatted through the owning type's locator contract. Empty
    when the URL carries no usable hint.
    """

    parent_id: CitationSourceId
    parent_name: str
    child: RecognitionChild | None = None
    identifier: str | None = None
    locator_hint: str = ""


# A recognizer tries one URL-resolution mechanism against a raw URL, returning a
# Recognition or None to abstain. ``recognize_url`` runs the ordered
# ``_RECOGNIZERS`` in turn; a future suffix/DOI mechanism is one more of these.
type Recognizer = Callable[[str], Recognition | None]


def _recognize_by_scheme(url: str) -> Recognition | None:
    """Recognizer 1 — identifier-scheme match.

    Try every registered scheme: the first whose pattern extracts an
    identifier *and* that has a seeded root wins — identify the scheme parent,
    then look up an existing child by that identifier. A scheme that
    matches but whose root isn't seeded is skipped (``continue``), not a
    miss: a later scheme may still own a seeded root. Returns parent +
    identifier, with the child when one already exists.
    """
    for key, driver in SCHEME_DRIVERS.items():
        extracted_id = driver.extract(url)
        if extracted_id is None:
            continue

        # Find the parent source that uses this scheme.
        parent = (
            CitationSource.objects.filter(identifier_key=key)
            .roots()
            .only("id", "name")
            .first()
        )
        if parent is None:
            continue

        # A structured start-time hint (a pasted ``?t=95``) becomes locator
        # text via the owning type's driver — the scheme declares where the
        # hint rides, the type parses and formats it; recognition just
        # carries the result.
        locator_hint = ""
        start_seconds = scheme_start_seconds_hint(key, url)
        if start_seconds is not None:
            type_driver = citation_type_driver(driver.spec.source_type)
            locator_hint = type_driver.format_locator_value(start_seconds) or ""

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
                    source_type=citation_source_type(child.source_type),
                ),
                identifier=extracted_id,
                locator_hint=locator_hint,
            )
        return Recognition(
            parent_id=parent.id,
            parent_name=parent.name,
            identifier=extracted_id,
            locator_hint=locator_hint,
        )
    return None


def _recognize_by_child_link(url: str) -> Recognition | None:
    """Recognizer 2 — exact child-link match.

    The full URL exactly matches a *child* source's linked URL — returns
    parent + child for instant re-citation. Children only: a root's own
    homepage link is ignored so the cite resolves to a page, not the
    abstract container.
    """
    child_link = (
        CitationSourceLink.objects.filter(
            url=url, citation_source__parent__isnull=False
        )
        .select_related("citation_source", "citation_source__parent")
        .first()
    )
    if not child_link:
        return None
    child = child_link.citation_source
    parent = child.parent
    # The parent__isnull=False filter guarantees a parent; this guard satisfies
    # the nullable-FK type (and is defense-in-depth) — unreachable in practice.
    if parent is None:
        return None
    return Recognition(
        parent_id=parent.pk,
        parent_name=parent.name,
        child=RecognitionChild(
            id=child.pk,
            name=child.name,
            skip_locator=child.skip_locator,
            source_type=citation_source_type(child.source_type),
        ),
    )


def _recognize_by_host(url: str) -> Recognition | None:
    """Recognizer 3 — recognition-host match (longest label-boundary suffix).

    Resolve the URL's normalized host to the root that owns it via
    ``CitationSourceRootDomain``, by **longest label-boundary suffix** — an
    asset subdomain (``s4.american-pinball.com``) resolves to its registrable
    root, while a more-specific seeded host (``twip.kineticist.com``) still
    wins over its parent domain for its own subtree. A **path-scoped** row (a
    shared CDN's per-tenant prefix) additionally requires the URL's path to sit
    under its prefix at a segment boundary; among matching rows host
    specificity dominates path specificity. Returns parent only, no
    identifier. The recognition host is an owned fact on the root, decoupled
    from the display ``homepage`` link — declared deliberately, never inferred
    and never via external HTTP. See ``docs/Citations.md``.

    Suffix matching is safe because ``CitationSourceRootDomain.clean()`` rejects
    any bare public suffix, so no stored host can over-match the unrelated sites
    beneath a public suffix (``gov.uk`` could never be a root that swallows
    ``dvla.gov.uk``).

    A syntactically-invalid host abstains: a malformed host (empty label,
    underscore, IP literal) can still yield a *valid ancestor* suffix
    (``www..american-pinball.com`` → ``.american-pinball.com`` →
    ``american-pinball.com``), so without this gate ``/search/`` would surface a
    confident-but-wrong match for garbage input. Recognition must not claim a
    page it can't honestly resolve; the host's shape is checked once, here. A URL
    too malformed for ``urlparse`` itself (an unterminated IPv6 bracket raises
    ``ValueError``) abstains the same way.
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

    # Narrow to the host's own label-boundary suffixes (a handful of rows at
    # most), then let longest_suffix_match pick the most specific. The root-only
    # filter is defense-in-depth for the app-level clean() invariant (rows
    # inserted via raw SQL / bulk that bypass it).
    candidates = [
        RootDomainMatch(
            source_id=row[0],
            source_name=row[1],
            host=Host(row[2]),
            path_prefix=PathPrefix(row[3]),
        )
        for row in CitationSourceRootDomain.objects.filter(
            host__in=label_suffixes(host),
            source__parent__isnull=True,
        ).values_list("source_id", "source__name", "host", "path_prefix")
    ]
    # On a shared multi-tenant CDN host only path-scoped rows carry honest
    # attribution — a bare row there (including a legitimate bare row on a
    # non-shared ancestor host, and junk a pre-guard write left behind) must
    # never absorb another tenant's URL; an unmatched tenant falls through to
    # no-match so cite-url's funnel can refuse it. And in either case a row
    # must satisfy the write invariant clean() enforces — a prefix lives on a
    # shared host only — so a prefixed row planted on an ordinary host through
    # a validation bypass can't split that site into path-scoped roots. Like
    # the root-only filter above, this discards only rows that bypassed
    # validation (plus, on a shared URL host, bare ancestor rows recognition
    # must not attribute to).
    if shared_host_for(host) is not None:
        candidates = [
            c
            for c in candidates
            if c.path_prefix and shared_host_for(c.host) is not None
        ]
    else:
        # A shared row host under a non-shared URL host is impossible (the
        # shared suffix would make the URL host shared too), so dropping
        # prefixed rows is exactly the row invariant here.
        candidates = [c for c in candidates if not c.path_prefix]
    best = longest_suffix_match(host, parsed.path, candidates)
    if best is None:
        return None
    return Recognition(parent_id=best.source_id, parent_name=best.source_name)


# The ordered recognizer pipeline: each tries one resolution mechanism over the
# shared scheme-registry + host machinery; the first to return a Recognition
# wins. Resolution order is load-bearing (scheme identity before exact link
# before host suffix) — see each recognizer's docstring. A new pre-processing
# step (archive-peel, DOI) becomes one more entry here.
_RECOGNIZERS: tuple[Recognizer, ...] = (
    _recognize_by_scheme,
    _recognize_by_child_link,
    _recognize_by_host,
)


def recognize_url(url: str) -> Recognition | None:
    """Try to recognize a pasted URL against known sources.

    Runs the ordered ``_RECOGNIZERS`` pipeline — identifier scheme, then exact
    child-link, then host suffix — and returns the first non-``None``
    ``Recognition``, or ``None`` if every recognizer abstains.
    """
    for recognizer in _RECOGNIZERS:
        recognition = recognizer(url)
        if recognition is not None:
            return recognition
    return None


# ---------------------------------------------------------------------------
# Classification: the exhaustive verdict every interactive surface switches on.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UrlDeliverer:
    """A deliverer copy — teach / auto-classify; never web-create.

    ``isbn`` is the URL-embedded work ISBN when the spec's declared shapes
    yield one (checksum-gated); ``kind`` is the suggested work kind (path
    hint, else the spec default) driving message wording and the create
    form's preselect.
    """

    spec: DelivererSpec
    isbn: str | None
    kind: CitationSourceTypeValue | None


@dataclass(frozen=True)
class UrlSchemeRecord:
    """A scheme record — cite via ``scheme:identifier``, never as a web page.

    ``recognition`` is present when the scheme's root is seeded (and then may
    carry an existing child for instant reuse); ``None`` for a URL matching a
    registered-but-unseeded scheme's pattern, which is still rejected as a
    web page so identity can't fork before the root lands.
    """

    label: str
    identifier: str
    recognition: Recognition | None


@dataclass(frozen=True)
class UrlIdentified:
    """An existing child covers this URL — reuse it.

    ``child`` restates ``recognition.child`` non-optionally, encoding the
    variant's invariant at the type level so consumers don't re-narrow.
    """

    recognition: Recognition
    child: RecognitionChild


@dataclass(frozen=True)
class UrlSiteOf:
    """A known site's page — mint a web child under ``recognition.parent_id``."""

    recognition: Recognition


@dataclass(frozen=True)
class UrlUnrecognized:
    """No verdict — the web-create funnel (new site root) applies."""


type UrlVerdict = (
    UrlDeliverer | UrlSchemeRecord | UrlIdentified | UrlSiteOf | UrlUnrecognized
)


def classify_url(url: str) -> UrlVerdict:
    """Classify a pasted URL into the verdict every interactive surface obeys.

    The design's spine: one exhaustive sum type instead of per-endpoint pre-checks,
    so a surface *cannot* skip a verb. Ordering is load-bearing:

    1. **Deliverer first, before any recognition** — prod data may already
       hold a misclassified deliverer root (an interactively-minted
       ``amazon.com`` site); a domain match must not short-circuit past the
       guardrail and mint another child under it.
    2. ``recognize_url`` — the existing identity pipeline (seeded scheme,
       exact child link, host suffix), re-named into explicit variants.
    3. ``recognize_scheme`` — a URL matching a registered-but-unseeded
       scheme's pattern is still a scheme record (the ``pages/`` rule),
       never a web page.
    """
    spec = deliverer_for_url(url)
    if spec is not None:
        return UrlDeliverer(
            spec=spec,
            isbn=embedded_isbn(url, spec),
            kind=suggested_work_kind(url, spec),
        )
    recognition = recognize_url(url)
    if recognition is not None:
        if recognition.identifier is not None:
            return UrlSchemeRecord(
                label=recognition.parent_name,
                identifier=recognition.identifier,
                recognition=recognition,
            )
        if recognition.child is not None:
            return UrlIdentified(recognition=recognition, child=recognition.child)
        return UrlSiteOf(recognition=recognition)
    scheme_recognition = recognize_scheme(url)
    if scheme_recognition is not None:
        return UrlSchemeRecord(
            label=scheme_recognition.label,
            identifier=scheme_recognition.identifier,
            recognition=None,
        )
    return UrlUnrecognized()


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
    parent_id: CitationSourceId,
    url: str,
    name: str = "",
    *,
    created_by: Actor,
) -> CitationSource:
    """Mint a validated web-page child under *parent_id*, linked at *url*.

    The child and its ``reference`` link are both ``full_clean``d, so a
    malformed *url* is rejected by the ``URLField`` format check rather than
    silently stored. The display name follows the ``web_child_name`` rule.

    ``created_by`` attributes both rows (required — citation attribution is
    non-null). Raises ``ValidationError`` on invalid input. Atomic, so a link
    that fails validation leaves no orphaned child behind.
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
    created_by: Actor,
) -> CitationSource:
    """Get-or-create the ``(root, identifier)`` scheme child under *root*.

    *identifier* is normalized through the root's scheme spec, so a raw URL and a
    bare id resolve to the same child. Idempotent — re-citing an identifier
    reuses its child. The child carries the ``{root.name} #{id}`` name and a
    canonical ``reference`` link, ``full_clean``d on first create.

    ``created_by`` attributes the child (required — citation attribution is
    non-null). Raises ``ValueError`` if *root* carries no known
    ``identifier_key`` scheme or the identifier is invalid for it.
    """
    driver = SCHEME_DRIVERS.get(root.identifier_key)
    if driver is None:
        raise ValueError(
            f"Root source {root.pk} has no known identifier scheme "
            f"({root.identifier_key!r})"
        )
    normalized = driver.normalize(identifier)
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
            # The scheme declares what its children mint as — a web scheme
            # mints web pages, a video scheme mints videos.
            source_type=driver.spec.source_type,
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
                url=driver.canonical_url(normalized),
                created_by=created_by,
                updated_by=created_by,
            )
            link.full_clean()
            link.save()
    return source


def get_or_create_external_source(
    scheme: str, identifier: str, *, created_by: Actor
) -> CitationSource:
    """Get-or-create the child ``CitationSource`` for ``scheme:identifier``.

    Resolves the root source owning *scheme* (e.g. the IPDB root), then
    get-or-creates the ``(root, identifier)`` child under it via
    ``get_or_create_scheme_child``.

    ``created_by`` attributes a newly minted child (required — citation
    attribution is non-null). Raises ``CitationSource.DoesNotExist`` if no root
    for *scheme* is seeded, and ``ValueError`` if the scheme or identifier is
    invalid.
    """
    if not is_known_scheme(scheme):
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
    return get_or_create_scheme_child(root, identifier, created_by=created_by)


def get_or_create_web_source(
    url: str, archive_url: str = "", *, created_by: Actor
) -> CitationSource:
    """Get-or-create the web ``CitationSource`` a raw ``url`` cites.

    When ``archive_url`` is given (e.g. a Wayback permalink), it is additively
    attached as a second ``archive``-typed link on the resolved source, so one
    citation carries both the live page and its durable snapshot. The
    attachment is idempotent (get-or-create by ``(source, url)``), so a
    re-applied patch never duplicates it, and a no-op when ``archive_url`` is
    empty or equal to ``url``.

    For citing a web page (forum post, archive scan, manufacturer page) that no
    identifier scheme covers. Routes through ``recognize_url`` so the URL
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

    ``created_by`` attributes a newly minted child and archive link (the citing
    patch's Source actor; required — citation attribution is non-null).
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
                # root, attributed to ``created_by`` (the citing patch's Source
                # actor) when given, else null.
                source = create_web_child(
                    recognition.parent_id, url, created_by=created_by
                )

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
                created_by=created_by,
                updated_by=created_by,
            )
            archive.full_clean()
            archive.save()
    return source


def get_isbn_source(isbn: str) -> CitationSource:
    """Resolve a seeded ``CitationSource`` by its ISBN — never minting one.

    The read-only counterpart to the two ``get_or_create_*`` helpers, for the
    ingestion path that cites an authored work (a book edition) rather than a
    web page or a platform record. A work is not derivable from its
    identifier the way a scheme record is — its author, publisher, year and
    place in a work/edition hierarchy are editorial facts — so an unseeded
    ISBN raises ``CitationSource.DoesNotExist`` instead of minting a nameless
    row. ``isbn`` is globally unique on the model, so resolution is exact and
    reuse is automatic: every cite of one work lands on the one shared source.

    A hit that has children is the abstract *work* (a multi-volume set, a book
    with several editions), not citable evidence, and raises too — an ISBN
    normally sits on the concrete edition, so this only fires on data that
    put one on a container.
    """
    source = CitationSource.objects.filter(isbn=isbn).first()
    if source is None:
        raise CitationSource.DoesNotExist(
            f"No CitationSource is seeded with ISBN {isbn!r}; declare the work "
            f"in a sources: block (or an earlier patch) before citing it."
        )
    if source.children.exists():
        raise ValueError(
            f"ISBN {isbn!r} is {source.name!r}, a work with editions under it — "
            f"cite the ISBN of the specific edition that holds the evidence."
        )
    return source


def get_slug_source(root_slug: str, child_slug: str) -> CitationSource:
    """Resolve a slug-addressed child (a periodical issue, a publisher's
    document) — never minting one.

    The authored-slug sibling of :func:`get_isbn_source`, for the ingestion
    path that cites a declared child of a slug-addressed root
    (``billboard:1945-09-29``, ``williams:wpc-95-schematic-manual``). The
    child is an editorial record — its date, name and place under its root
    are facts someone declares — so an undeclared pair raises
    ``CitationSource.DoesNotExist`` instead of minting a nameless row. The message names the known scheme keys because a typo'd
    scheme cite (``ipddb:4443``) parses as this form and lands here — the
    did-you-mean for that mistake.

    A hit that has children is an abstract container, not citable evidence
    (the reasoning of :func:`get_isbn_source`'s work-with-editions guard),
    and raises too. The parent must be a root — the model's ``clean()``
    enforces two-level nesting for slug-addressed types, and the single
    ``parent__parent__isnull`` hop here mirrors that.
    """
    source = CitationSource.objects.filter(
        slug=child_slug, parent__slug=root_slug, parent__parent__isnull=True
    ).first()
    if source is None:
        known = ", ".join(sorted(known_scheme_keys()))
        raise CitationSource.DoesNotExist(
            f"No citation source child {root_slug}:{child_slug} exists; declare "
            f"the child (a periodical issue, a publisher's document) in a "
            f"sources: block (or an earlier patch) before citing it. (If you "
            f"meant a scheme record, the known schemes are: {known}.)"
        )
    if source.children.exists():
        raise ValueError(
            f"{root_slug}:{child_slug} is {source.name!r}, a container with "
            f"children under it — cite the specific child that holds the "
            f"evidence."
        )
    return source
