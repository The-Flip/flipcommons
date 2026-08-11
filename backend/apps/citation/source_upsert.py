"""Get-or-create citation sources for the data-patch ``sources:`` block.

**Additive-only**: ``ensure_source`` creates a missing source or backfills a
missing link, but never overwrites an existing row or link. A collision is a
warning, never a failure — so a user-created source can't wedge the ingest
queue. See ``docs/DataPatches.md``.

Three shapes, dispatched on the node: a slug-addressed child (``parent:`` set,
a periodical issue), a slug-addressed root (``slug:`` set, a periodical), and the
plain root every other type declares — the original host-then-ISBN-then-name
chain, untouched. Nesting is expressed by ``parent:``, never by structure.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict
from urllib.parse import urlparse

from apps.citation.citation_types import (
    SourceType,
    citation_type_spec,
    scheme_root_citation_source_info,
)
from apps.citation.hosts import (
    Host,
    PathPrefix,
    normalize_host,
    normalize_path_prefix,
)
from apps.citation.source_node import SourceLinkNode, SourceNode
from apps.core.validators import SLUG_FORMAT_MESSAGE, SLUG_RE

if TYPE_CHECKING:
    from apps.actors.models import Actor
    from apps.citation.models import CitationSource


class SourceFields(TypedDict):
    """The model-column subset of a patch source node — no parent, links or children.

    This is ``SourceNode`` minus its ``parent``/``links``/``children`` keys: the
    exact set of kwargs that construct a ``CitationSource`` row (``parent`` is a
    slug *reference*, resolved to the FK by the upsert). Naming each column
    (rather than a ``dict[str, object]`` bag) lets ``_lookup_source`` read
    ``name`` as a ``str`` and ``isbn`` as ``str | None`` without a cast.
    """

    name: str
    source_type: str
    author: NotRequired[str]
    publisher: NotRequired[str]
    year: NotRequired[int]
    month: NotRequired[int]
    day: NotRequired[int]
    date_note: NotRequired[str]
    isbn: NotRequired[str]
    description: NotRequired[str]
    identifier_key: NotRequired[str]
    slug: NotRequired[str]


class SourceUpsertResult(NamedTuple):
    """Outcome of one ``ensure_source`` call, tallied by the caller.

    Source-agnostic by design: the data-patch hook reads these counts into its
    ``RunReport`` (a catalog type the citation app must not import).
    """

    source_created: bool
    links_created: int


# ---------------------------------------------------------------------------
# Source lookup + create primitives
# ---------------------------------------------------------------------------


class SourceMatch(NamedTuple):
    """The result of a soft-natural-key lookup: the first match and the count.

    ``match_count`` can exceed 1 on the ``(name, source_type)`` path (the caller
    warns and operates on ``source``); it is 0/1 on the unique ``isbn`` path.
    (Not named ``count`` — that would shadow ``tuple.count``.)
    """

    source: CitationSource | None
    match_count: int


def _source_fields(node: SourceNode) -> SourceFields:
    """Project a patch source node onto its model columns (drop parent/links/children).

    Built key-by-key rather than by comprehension so each value keeps its column
    type: ``SourceNode.items()`` erases to ``object``, but copying a known key
    preserves ``str``/``int``. Omitted optional keys stay omitted (not ``None``),
    so a found-row divergence check never compares against a phantom ``None``.
    """
    fields: SourceFields = {"name": node["name"], "source_type": node["source_type"]}
    if "author" in node:
        fields["author"] = node["author"]
    if "publisher" in node:
        fields["publisher"] = node["publisher"]
    if "year" in node:
        fields["year"] = node["year"]
    if "month" in node:
        fields["month"] = node["month"]
    if "day" in node:
        fields["day"] = node["day"]
    if "date_note" in node:
        fields["date_note"] = node["date_note"]
    if "isbn" in node:
        fields["isbn"] = node["isbn"]
    if "description" in node:
        fields["description"] = node["description"]
    if "identifier_key" in node:
        fields["identifier_key"] = node["identifier_key"]
    if "slug" in node:
        fields["slug"] = node["slug"]
    return fields


def _lookup_source(fields: SourceFields) -> SourceMatch:
    """Find an existing source by the soft natural key.

    Keys on ``isbn`` when present (DB-unique → at most one), else on
    ``(name, source_type)`` scoped to parentless rows (count can exceed 1; the
    caller decides what to do).

    The ``(name, source_type)`` match is root-scoped because only *roots* are
    created here: a same-named child (one a ``cite:`` minted, say) must not
    shadow the root it should create — otherwise the root is never made and
    links land on a child, where ``recognize_url`` can't see them. The ``isbn``
    path is deliberately **not** scoped: ``isbn`` is globally unique (a flat
    book root carries one), and excluding a child that holds the isbn would
    force a create that violates the unique constraint.
    """
    from apps.citation.models import CitationSource

    isbn = fields.get("isbn")
    if isbn:
        obj = CitationSource.objects.filter(isbn=isbn).first()
        return SourceMatch(obj, 1 if obj is not None else 0)
    qs = CitationSource.objects.filter(
        name=fields["name"], source_type=fields["source_type"]
    ).roots()
    return SourceMatch(qs.first(), qs.count())


def _create_source(
    fields: SourceFields, *, actor: Actor, parent: CitationSource | None = None
) -> CitationSource:
    """Validate + save a new ``CitationSource`` under ``parent`` (default root)."""
    from apps.citation.models import CitationSource

    obj = CitationSource(**fields, parent=parent, created_by=actor, updated_by=actor)
    obj.full_clean()
    obj.save()
    return obj


def _create_link(source: CitationSource, link: SourceLinkNode, *, actor: Actor) -> None:
    """Validate + save a single ``CitationSourceLink`` on ``source``."""
    from apps.citation.models import CitationSourceLink

    obj = CitationSourceLink(
        citation_source=source,
        url=link["url"],
        label=link.get("label", ""),
        link_type=link["link_type"],
        created_by=actor,
        updated_by=actor,
    )
    obj.full_clean()
    obj.save()


class DeclaredDomain(NamedTuple):
    """One declared recognition slice: a host and its optional path prefix.

    ``path_prefix`` is ``""`` for an ordinary whole-host declaration and a
    normalized prefix for a shared-CDN tenant slice
    (``img1.wsimg.com/blobby/go/<uuid>``). Both halves are normalized, so
    exact-pair dedup and DB resolution compare verbatim.
    """

    host: Host
    path_prefix: PathPrefix

    def __str__(self) -> str:
        return f"{self.host}{self.path_prefix}"


def _declared_homepage_hosts(links: Sequence[SourceLinkNode]) -> list[DeclaredDomain]:
    """Recognition hosts a node declares via its ``homepage`` links, bare.

    Only ``homepage``-typed links contribute a recognition host (matching the
    backfill and the create paths); other link types are display-only. A
    homepage host is always a **bare** declaration — a homepage URL's path is
    the page, not a recognition scope. Each URL's hostname is parsed and
    normalized; a ``None`` hostname is skipped (honoring ``hosts``' None→skip
    contract). Order-preserving and de-duplicated.
    """
    domains: list[DeclaredDomain] = []
    for link in links:
        if link["link_type"] != "homepage":
            continue
        hostname = urlparse(link["url"]).hostname
        if hostname is None:
            continue
        host = normalize_host(hostname)
        declared = DeclaredDomain(host=host, path_prefix=PathPrefix(""))
        if host and declared not in domains:
            domains.append(declared)
    return domains


def _declared_domains(node: SourceNode) -> list[DeclaredDomain]:
    """Recognition slices a node declares via the ``domains:`` verb.

    Forgiving input: each entry may be a bare host (``oldpin.com``), a full URL
    (``https://oldpin.com/``), or either form carrying a path — the shared-CDN
    tenant shape (``img1.wsimg.com/blobby/go/<uuid>``). **The path is
    meaningful**: it becomes the row's ``path_prefix``, so a full-URL entry
    with a path declares a path-scoped slice rather than silently registering
    the bare host (the misattribution the shared-host guard exists to
    prevent). Unlike a homepage host this is a pure recognition declaration —
    no display side, no rounding. Order-preserving and de-duplicated by exact
    pair; the DNS/public-suffix/shared-host guards are applied later by
    :func:`validate_source_node` and the model's ``clean()`` at mint.

    A malformed URL-shaped entry whose parse raises (an unbalanced IPv6
    bracket, ``https://[::1/page``) falls back to the raw string as a host, so
    the model guard rejects it as a clean ``ValidationError`` (→ ``PatchError``)
    at read phase rather than letting a raw ``ValueError`` escape as a
    traceback. Domains have no upstream URLValidator the way homepage links do.
    """
    domains: list[DeclaredDomain] = []
    for entry in node.get("domains", []):
        try:
            parsed = urlparse(entry)
            hostname = parsed.hostname
            url_path = parsed.path
        except ValueError:
            hostname = None
            url_path = ""
        if hostname is not None:
            raw_host, raw_path = hostname, url_path
        else:
            # A schemeless entry parses entirely into .path — split the first
            # segment off as the host, the remainder (if any) as the prefix.
            raw_host, _, remainder = entry.partition("/")
            raw_path = f"/{remainder}" if remainder else ""
        declared = DeclaredDomain(
            host=normalize_host(raw_host),
            path_prefix=normalize_path_prefix(raw_path),
        )
        if declared.host and declared not in domains:
            domains.append(declared)
    return domains


def _declared_recognition_hosts(node: SourceNode) -> list[DeclaredDomain]:
    """The node's full recognition set: ``homepage`` links ∪ ``domains:``.

    One unified set so resolution (:func:`_roots_owning_hosts`) and minting
    (:func:`_ensure_root_domains`) can never diverge on what identifies a root.
    Homepage hosts come first (display-and-recognition, always bare), then
    declared-only ``domains:`` slices; de-duplicated across both by exact
    ``(host, path_prefix)`` pair, order-preserving.
    """
    domains = _declared_homepage_hosts(node.get("links", []))
    for declared in _declared_domains(node):
        if declared not in domains:
            domains.append(declared)
    return domains


def _roots_owning_hosts(domains: Sequence[DeclaredDomain]) -> list[CitationSource]:
    """The distinct **root** sources that already own any of the given slices.

    Exact ``(host, path_prefix)`` lookup against ``CitationSourceRootDomain`` —
    **never** the longest-suffix matcher recognition uses. Dedup keys on the
    literal pair so a deliberately-declared subdomain root
    (``twip.kineticist.com`` under an existing ``kineticist.com``) is treated
    as a distinct, unseeded host, not folded into its parent domain — and one
    shared CDN host's tenant slices resolve independently. One ``host__in``
    query, pair-matched in Python. Root-scoped (``parent__isnull``) because
    only a root is a valid match target; a slice illegitimately held by a
    child (a ``clean()`` bypass) is handled defensively by
    :func:`_ensure_root_domains`, not matched here. Distinct by pk — one root
    may own several of the slices.
    """
    from apps.citation.models import CitationSourceRootDomain

    wanted = set(domains)
    rows = CitationSourceRootDomain.objects.filter(
        host__in=[d.host for d in domains], source__parent__isnull=True
    ).select_related("source")
    owners = {
        row.source_id: row.source
        for row in rows
        if DeclaredDomain(Host(row.host), PathPrefix(row.path_prefix)) in wanted
    }
    return list(owners.values())


def _spans_two_roots_warning(name: str, host_roots: Sequence[CitationSource]) -> str:
    """The warning for a node whose recognition hosts span >1 existing root.

    Such a node skips whole at apply — picking one owner and minting the others
    would trip the ``host`` ``unique`` and wedge the queue. Names each owning root
    (the merge backlog until citation gardening ships).
    """
    owners = ", ".join(sorted(repr(r.name) for r in host_roots))
    return (
        f"Citation source {name!r} declares recognition hosts already owned "
        f"by {len(host_roots)} different roots ({owners}); skipped the node "
        f"(no writes) to avoid a domain collision. Resolve the duplicate "
        f"roots first."
    )


def _ensure_root_domains(
    source: CitationSource,
    domains: Sequence[DeclaredDomain],
    *,
    warnings: list[str],
    actor: Actor,
) -> None:
    """Additively mint a recognition domain on ``source`` for each unowned slice.

    Each ``(host, path_prefix)`` pair is resolved against **every** existing
    owner (not just ``source``, and not root-scoped): a slice ``source``
    already owns is a no-op; a slice owned by a *different* source warns and is
    skipped — never minted-over, so the pair ``unique`` cannot trip and wedge
    the patch queue (honoring the module's "a collision is a warning, never a
    failure" contract). This is the backstop for a slice the root-scoped
    :func:`_roots_owning_hosts` couldn't see — e.g. one a child illegitimately
    holds. Otherwise the row is ``full_clean``ed (firing the root-only /
    normalization / shared-host guards) and saved.
    """
    from apps.citation.models import CitationSourceRootDomain

    for declared in domains:
        owner = (
            CitationSourceRootDomain.objects.filter(
                host=declared.host, path_prefix=declared.path_prefix
            )
            .select_related("source")
            .first()
        )
        if owner is not None:
            if owner.source_id != source.pk:
                warnings.append(
                    f"Recognition host {str(declared)!r} is already owned by "
                    f"{owner.source.name!r}; not minted on {source.name!r}."
                )
            continue
        domain = CitationSourceRootDomain(
            source=source,
            host=declared.host,
            path_prefix=declared.path_prefix,
            created_by=actor,
            updated_by=actor,
        )
        domain.full_clean()
        domain.save()


# ---------------------------------------------------------------------------
# Read-phase validation + additive get-or-create
# ---------------------------------------------------------------------------


def _validate_slug_addressing(
    node: SourceNode, declared_root_slugs: Collection[str]
) -> None:
    """Read-phase checks for the ``slug``/``parent`` verbs on a source node.

    Explicit (not via the model's CHECKs — those are excluded from the in-memory
    ``full_clean`` because the partial-unique validations would reject the
    legitimate re-declare case): ``slug``/``parent`` only on a slug-addressed
    type, and required there; both in the system slug grammar; a root slug clear
    of the reserved cite handles; and every ``parent:`` resolving to a root of
    the same type — already in the DB, or declared elsewhere in the same block
    (``declared_root_slugs``, the caller's parentless-node slugs). The
    committed-state read is what lets a typo'd parent fail as a clean
    ``PatchError`` naming the node, before the batch writes anything, instead of
    skipping at apply. A parented node may not declare recognition ``domains`` —
    those are root-only.
    """
    from django.core.exceptions import ValidationError

    from apps.citation.models import (
        CITATION_SOURCE_SLUG_MAX_LENGTH,
        CitationSource,
        reserved_cite_handles,
    )

    slug = node.get("slug", "")
    parent_ref = node.get("parent", "")
    source_type = node["source_type"]
    addressed = (
        source_type in SourceType.values
        and citation_type_spec(source_type).slug_addressed
    )
    if not addressed:
        # An invalid source_type is the field validator's error (caught by the
        # model full_clean before this runs); here it just isn't slug-addressed.
        for key, value in (("slug", slug), ("parent", parent_ref)):
            if value:
                raise ValidationError(
                    {
                        key: f"'{key}' is only valid on a slug-addressed type "
                        f"(a {source_type} source is addressed another way)"
                    }
                )
        return
    if not slug:
        raise ValidationError(
            {
                "slug": f"a {source_type} source is slug-addressed and requires "
                f"an authored 'slug'"
            }
        )
    if not SLUG_RE.fullmatch(slug):
        raise ValidationError({"slug": SLUG_FORMAT_MESSAGE})
    # Length is normally the model field's check, but ``slug`` is excluded
    # from the read-phase full_clean (its partial uniques would reject the
    # found case) — without this, an overlong slug raises mid-apply, wedging
    # the queue instead of failing with a clean per-node error.
    if len(slug) > CITATION_SOURCE_SLUG_MAX_LENGTH:
        raise ValidationError(
            {"slug": f"slug exceeds {CITATION_SOURCE_SLUG_MAX_LENGTH} characters"}
        )
    if parent_ref:
        if not SLUG_RE.fullmatch(parent_ref):
            raise ValidationError({"parent": SLUG_FORMAT_MESSAGE})
        if len(parent_ref) > CITATION_SOURCE_SLUG_MAX_LENGTH:
            raise ValidationError(
                {
                    "parent": f"parent exceeds "
                    f"{CITATION_SOURCE_SLUG_MAX_LENGTH} characters"
                }
            )
        if node.get("domains"):
            raise ValidationError({"domains": "recognition domains live on roots only"})
        if parent_ref not in declared_root_slugs and not (
            CitationSource.objects.roots()
            .filter(slug=parent_ref, source_type=source_type)
            .exists()
        ):
            raise ValidationError(
                {
                    "parent": f"parent {parent_ref!r} is neither an existing "
                    f"{source_type} root nor declared in this patch's sources: "
                    f"block"
                }
            )
    elif slug in reserved_cite_handles():
        raise ValidationError(
            {
                "slug": f"{slug!r} is reserved — it is the cite prefix of another "
                f"citation form (isbn: or a scheme key)"
            }
        )


def validate_source_node(
    node: SourceNode, *, declared_root_slugs: Collection[str] = ()
) -> None:
    """Field-validate a patch ``sources:`` node in memory (no writes).

    Builds the ``CitationSource``, its ``CitationSourceLink`` rows and its
    ``CitationSourceRootDomain`` recognition hosts and runs ``full_clean`` on them
    with **DB-uniqueness off** — a node that legitimately matches an existing row
    (the additive get-or-create's "found" case) must not be rejected, and an
    in-memory link/domain's required FK is unset. Catches bad ``source_type``,
    out-of-range dates, invalid ``identifier_key``, malformed URL, invalid
    ``link_type``, duplicate declared link URLs, and a recognition host that isn't
    a DNS name or is a bare public suffix. The host set is the unified
    ``homepage ∪ domains`` set, so a bad **homepage** host fails here rather
    than crashing mid-apply at mint. Validating through the model's ``clean()``
    keeps the host guard single-sourced (no forked predicate check). The
    ``slug``/``parent`` verbs are validated by
    :func:`_validate_slug_addressing` (see there for why they sit outside the
    model ``full_clean``); ``declared_root_slugs`` is the same-block declared
    parentless slugs a ``parent:`` may resolve against. Raises
    :class:`django.core.exceptions.ValidationError`; the patch adapter maps it
    to a ``PatchError`` naming the node, before the batch writes anything.
    """
    from django.core.exceptions import ValidationError

    from apps.citation.models import (
        CitationSource,
        CitationSourceLink,
        CitationSourceRootDomain,
    )

    # Validate field/host shape only — ``created_by``/``updated_by`` are stamped
    # at write time (``ensure_source``), not on these throwaway instances, so
    # exclude them from the non-null check alongside the unset parent FK.
    # ``slug`` is excluded because its partial-unique constraints would reject
    # the legitimate found case; ``_validate_slug_addressing`` owns it instead.
    attribution = ["created_by", "updated_by"]
    source = CitationSource(**_source_fields(node))
    source.full_clean(exclude=[*attribution, "slug"], validate_unique=False)

    _validate_slug_addressing(node, declared_root_slugs)

    seen_urls: set[str] = set()
    for link in node.get("links", []):
        url = link["url"]
        if url in seen_urls:
            raise ValidationError({"links": f"duplicate declared link URL {url!r}"})
        seen_urls.add(url)
        obj = CitationSourceLink(
            url=url,
            label=link.get("label", ""),
            link_type=link["link_type"],
        )
        obj.full_clean(exclude=["citation_source", *attribution], validate_unique=False)

    for declared in _declared_recognition_hosts(node):
        domain = CitationSourceRootDomain(
            host=declared.host, path_prefix=declared.path_prefix
        )
        # validate_constraints=False alongside validate_unique=False: the
        # (host, path_prefix) UniqueConstraint is validated by the constraints
        # pass (not the unique pass), and a node legitimately re-declaring a
        # domain already in the DB must not be rejected here. clean() still
        # runs every real guard; the DB enforces the constraints at mint.
        domain.full_clean(
            exclude=["source", *attribution],
            validate_unique=False,
            validate_constraints=False,
        )

    _validate_scheme_root_citation_source_info(node)


def _validate_scheme_root_citation_source_info(node: SourceNode) -> None:
    """Hold a scheme root's declaration to its registered root facts.

    A ``sources:`` node carrying an ``identifier_key`` is declaring a scheme's
    platform root, and the scheme registry is operationally authoritative for
    those: the declared name, homepage URL and recognition-host set must match
    the spec's ``root_citation_source_info`` exactly, so the registry and the
    seeded row can't silently disagree (a mistyped root would mint children
    that never match the spec's canonical facts). Non-scheme nodes are
    unconstrained. Unknown keys are the field validator's error (choices),
    checked before this runs.
    """
    from django.core.exceptions import ValidationError

    key = node.get("identifier_key", "")
    info = scheme_root_citation_source_info(key) if key else None
    if info is None:
        return
    problems: list[str] = []
    if node["name"] != info.name:
        problems.append(f"name must be {info.name!r} (declared {node['name']!r})")
    homepage_urls = [
        link["url"] for link in node.get("links", []) if link["link_type"] == "homepage"
    ]
    if info.homepage_url not in homepage_urls:
        problems.append(
            f"homepage link {info.homepage_url!r} must be declared "
            f"(declared homepages: {homepage_urls!r})"
        )
    declared_domains = set(_declared_recognition_hosts(node))
    # A scheme root's registered recognition hosts are always bare — path
    # scoping is a shared-CDN concern no platform root has.
    expected = {
        DeclaredDomain(host=Host(host), path_prefix=PathPrefix(""))
        for host in info.recognition_hosts
    }
    if declared_domains != expected:
        problems.append(
            f"recognition hosts must be {sorted(info.recognition_hosts)!r} "
            f"(declared {sorted(str(d) for d in declared_domains)!r})"
        )
    if problems:
        raise ValidationError(
            {
                "identifier_key": (
                    f"scheme root {key!r} must match its registered root info: "
                    + "; ".join(problems)
                )
            }
        )


def _ensure_links(
    obj: CitationSource,
    links: Sequence[SourceLinkNode],
    *,
    warnings: list[str],
    actor: Actor,
) -> int:
    """Additively ensure each declared link on a found source.

    Create a missing URL, no-op an identical one, warn on a same-URL link whose
    type/label diverge — never overwrite. Returns the number created.
    """
    existing = {link.url: link for link in obj.links.all()}
    links_created = 0
    for link in links:
        url = link["url"]
        current = existing.get(url)
        if current is None:
            _create_link(obj, link, actor=actor)
            links_created += 1
        elif current.link_type != link["link_type"] or current.label != link.get(
            "label", ""
        ):
            warnings.append(
                f"Citation source {obj.name!r} link {url!r} already exists with a "
                f"different type/label; left unchanged."
            )
    return links_created


def ensure_source(
    node: SourceNode,
    *,
    actor: Actor,
    warnings: list[str],
) -> SourceUpsertResult:
    """Additively get-or-create one ``sources:`` node. Never overwrites.

    Dispatch on the node's shape: ``parent:`` present → a slug-addressed child
    under a slug-resolved root; ``slug:`` present → a slug-addressed root; else
    the original host-then-ISBN-then-name chain (:func:`_ensure_plain_root`),
    which still owns every non-slug-addressed node. All branches share the
    additive semantics: create if absent, warn on declared-field divergence,
    backfill missing links, never raise on a collision.
    """
    if "parent" in node:
        return _ensure_slug_child(node, actor=actor, warnings=warnings)
    if "slug" in node:
        return _ensure_slug_root(node, actor=actor, warnings=warnings)
    return _ensure_plain_root(node, actor=actor, warnings=warnings)


def _ensure_slug_root(
    node: SourceNode, *, actor: Actor, warnings: list[str]
) -> SourceUpsertResult:
    """Get-or-create a slug-addressed root, resolved by its authored slug.

    The slug is the identity — the name key never runs, so a renamed periodical
    re-declared under its slug is found, not duplicated. Recognition-domain
    handling matches the plain-root path (a periodical may declare a homepage).
    """
    from apps.citation.models import CitationSource

    fields = _source_fields(node)
    links = node.get("links", [])
    recognition_domains = _declared_recognition_hosts(node)
    obj = CitationSource.objects.roots().filter(slug=fields["slug"]).first()
    if obj is None:
        obj = _create_source(fields, actor=actor)
        for link in links:
            _create_link(obj, link, actor=actor)
        _ensure_root_domains(obj, recognition_domains, warnings=warnings, actor=actor)
        return SourceUpsertResult(source_created=True, links_created=len(links))
    divergent = sorted(k for k, v in fields.items() if getattr(obj, k) != v)
    if divergent:
        warnings.append(
            f"Citation source {fields['name']!r} resolved by slug "
            f"{fields['slug']!r} to existing root {obj.name!r}; declared fields "
            f"{divergent} differ and were left unchanged."
        )
    links_created = _ensure_links(obj, links, warnings=warnings, actor=actor)
    _ensure_root_domains(obj, recognition_domains, warnings=warnings, actor=actor)
    return SourceUpsertResult(source_created=False, links_created=links_created)


def _ensure_slug_child(
    node: SourceNode, *, actor: Actor, warnings: list[str]
) -> SourceUpsertResult:
    """Get-or-create a slug-addressed child under its slug-resolved parent root.

    The parent resolved at read phase (committed or same-block, parentless
    processed first), so a miss here means the state changed between read and
    apply — warn and skip the node whole, honoring the module's never-fail
    contract. A declared child whose *name* matches an existing sibling under a
    different slug warns too (two campaigns inventing ``1945-09-29`` and
    ``sep-29-1945`` for one issue) but still creates: a cite in this patch may
    reference the new slug, and a human merges duplicates later. Children mint
    no recognition domains — those are root-only.
    """
    from apps.citation.models import CitationSource

    fields = _source_fields(node)
    links = node.get("links", [])
    parent_slug = node["parent"]
    parent = (
        CitationSource.objects.roots()
        .filter(slug=parent_slug, source_type=fields["source_type"])
        .first()
    )
    if parent is None:
        warnings.append(
            f"Citation source {fields['name']!r} declares parent "
            f"{parent_slug!r}, which no longer resolves to a "
            f"{fields['source_type']} root; skipped the node (no writes)."
        )
        return SourceUpsertResult(source_created=False, links_created=0)
    obj = CitationSource.objects.filter(parent=parent, slug=fields["slug"]).first()
    if obj is None:
        namesake = (
            CitationSource.objects.filter(parent=parent, name=fields["name"])
            .exclude(slug=fields["slug"])
            .first()
        )
        if namesake is not None:
            warnings.append(
                f"Citation source {fields['name']!r} (slug {fields['slug']!r}) "
                f"has the same name as existing sibling slug {namesake.slug!r} "
                f"under {parent.name!r} — possible duplicate issue; created "
                f"anyway."
            )
        obj = _create_source(fields, actor=actor, parent=parent)
        for link in links:
            _create_link(obj, link, actor=actor)
        return SourceUpsertResult(source_created=True, links_created=len(links))
    divergent = sorted(k for k, v in fields.items() if getattr(obj, k) != v)
    if divergent:
        warnings.append(
            f"Citation source {fields['name']!r} resolved by slug "
            f"{parent_slug}:{fields['slug']} to an existing child; declared "
            f"fields {divergent} differ and were left unchanged."
        )
    links_created = _ensure_links(obj, links, warnings=warnings, actor=actor)
    return SourceUpsertResult(source_created=False, links_created=links_created)


def _ensure_plain_root(
    node: SourceNode,
    *,
    actor: Actor,
    warnings: list[str],
) -> SourceUpsertResult:
    """Additively get-or-create a flat (root) citation source. Never overwrites.

    Resolution order, host before name:

    1. **By recognition host.** Resolve the node's declared recognition hosts
       (``homepage`` links ∪ ``domains:``) to the roots that already own them
       (exact host, not suffix). Hosts owned by **>1 distinct root** → warn
       (naming each owning root, the merge backlog until gardening ships) and
       **skip the node, no writes** (picking one and minting the other would trip
       the ``host`` ``unique`` and wedge the queue). Exactly **one** owning root →
       that's the match (host wins even if a differently-named root shares the
       ``(name, source_type)`` — the re-declare-under-a-new-name case, or a rebrand
       declaring its old domain in ``domains:``).
    2. **By soft natural key.** No host match → fall back to ``isbn`` /
       ``(name, source_type)`` (root-scoped so a same-named child can't shadow
       the root), so a same-named root merely gaining a *new* recognition host is
       found, not duplicated. On >1 match, operate on the first and warn. Still
       absent → create the source + all its declared links.

    On the matched-or-created root, additively ensure each declared link (create
    a missing URL, no-op an identical one, warn on a same-URL/different-type one)
    and mint a ``CitationSourceRootDomain`` for every declared recognition host it
    doesn't already own. Never raises on a collision; the caller tallies counts.
    """
    fields = _source_fields(node)
    name = fields["name"]
    source_type = fields["source_type"]
    links = node.get("links", [])
    recognition_domains = _declared_recognition_hosts(node)

    # Resolve by recognition host first; host identity wins over the name key.
    host_roots = _roots_owning_hosts(recognition_domains)
    if len(host_roots) > 1:
        warnings.append(_spans_two_roots_warning(name, host_roots))
        return SourceUpsertResult(source_created=False, links_created=0)

    obj: CitationSource | None
    matched_by_host = bool(host_roots)
    if matched_by_host:
        obj = host_roots[0]
    else:
        obj, match_count = _lookup_source(fields)
        if match_count > 1:
            warnings.append(
                f"Citation source ({name!r}, {source_type!r}) matched "
                f"{match_count} rows; operated on the first."
            )

    if obj is None:
        obj = _create_source(fields, actor=actor)
        for link in links:
            _create_link(obj, link, actor=actor)
        _ensure_root_domains(obj, recognition_domains, warnings=warnings, actor=actor)
        return SourceUpsertResult(source_created=True, links_created=len(links))

    # Found: never overwrite the row; warn on any declared-field divergence.
    # A host match under a different name is expected (re-declare under a new name),
    # so name that case explicitly rather than claiming the declared name exists.
    divergent = sorted(k for k, v in fields.items() if getattr(obj, k) != v)
    if divergent and matched_by_host:
        warnings.append(
            f"Citation source {name!r} resolved by recognition host to existing "
            f"root {obj.name!r}; declared fields {divergent} differ and were left "
            f"unchanged."
        )
    elif divergent:
        warnings.append(
            f"Citation source {name!r} already exists; declared fields "
            f"{divergent} differ from the stored values and were left unchanged."
        )

    links_created = _ensure_links(obj, links, warnings=warnings, actor=actor)
    _ensure_root_domains(obj, recognition_domains, warnings=warnings, actor=actor)
    return SourceUpsertResult(source_created=False, links_created=links_created)
