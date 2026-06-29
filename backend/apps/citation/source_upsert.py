"""Get-or-create citation sources for the data-patch ``sources:`` block.

Flat (roots only) and **additive-only**: ``ensure_root_source`` creates a
missing source or backfills a missing link, but never overwrites an existing row
or link. A collision is a warning, never a failure — so a user-created source
can't wedge the ingest queue. See ``docs/DataPatches.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict
from urllib.parse import urlparse

from apps.citation.hosts import Host, normalize_host
from apps.citation.source_node import SourceLinkNode, SourceNode

if TYPE_CHECKING:
    from apps.actors.models import Actor
    from apps.citation.models import CitationSource


class SourceFields(TypedDict):
    """The model-column subset of a patch source node — no parent, links or children.

    This is ``SourceNode`` minus its ``links``/``children`` keys: the exact set
    of kwargs that construct a ``CitationSource`` row. Naming each column (rather
    than a ``dict[str, object]`` bag) lets ``_lookup_source`` read ``name`` as a
    ``str`` and ``isbn`` as ``str | None`` without a cast.
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


class SourceUpsertResult(NamedTuple):
    """Outcome of one ``ensure_root_source`` call, tallied by the caller.

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


def _declared_homepage_hosts(links: Sequence[SourceLinkNode]) -> list[Host]:
    """Normalized recognition hosts a node declares via its ``homepage`` links.

    Only ``homepage``-typed links contribute a recognition host (matching the
    backfill and the create paths); other link types are display-only. Each
    URL's hostname is parsed and normalized; a ``None`` hostname is skipped
    (honoring ``hosts``' None→skip contract). Order-preserving and de-duplicated.
    """
    hosts: list[Host] = []
    for link in links:
        if link["link_type"] != "homepage":
            continue
        hostname = urlparse(link["url"]).hostname
        if hostname is None:
            continue
        host = normalize_host(hostname)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _declared_domains_hosts(node: SourceNode) -> list[Host]:
    """Normalized recognition hosts a node declares via the ``domains:`` verb.

    Forgiving input: each entry may be a bare host (``oldpin.com``) or a full URL
    (``https://oldpin.com/``); ``urlparse(entry).hostname or entry`` lands both on
    the same host before :func:`normalize_host`. Unlike a homepage host this is a
    pure recognition declaration — no display side, no rounding. Order-preserving
    and de-duplicated; the universal DNS/public-suffix guard is applied later by
    :func:`validate_root_source` and the model's ``clean()`` at mint.

    A malformed entry whose ``.hostname`` access raises (an unbalanced IPv6
    bracket, ``https://[::1/page``) falls back to the raw string, so the model
    guard rejects it as a clean ``ValidationError`` (→ ``PatchError``) at read
    phase rather than letting a raw ``ValueError`` escape as a traceback. Domains
    have no upstream URLValidator the way homepage links do.
    """
    hosts: list[Host] = []
    for entry in node.get("domains", []):
        try:
            hostname = urlparse(entry).hostname
        except ValueError:
            hostname = None
        host = normalize_host(hostname or entry)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _declared_recognition_hosts(node: SourceNode) -> list[Host]:
    """The node's full recognition-host set: ``homepage`` links ∪ ``domains:``.

    One unified set so resolution (:func:`_roots_owning_hosts`) and minting
    (:func:`_ensure_root_domains`) can never diverge on what identifies a root.
    Homepage hosts come first (display-and-recognition), then declared-only
    ``domains:`` hosts; de-duplicated across both, order-preserving.
    """
    hosts = _declared_homepage_hosts(node.get("links", []))
    for host in _declared_domains_hosts(node):
        if host not in hosts:
            hosts.append(host)
    return hosts


def _roots_owning_hosts(hosts: Sequence[Host]) -> list[CitationSource]:
    """The distinct **root** sources that already own any of the given hosts.

    Exact-host lookup against ``CitationSourceRootDomain`` — **never** the
    longest-suffix matcher recognition uses. Dedup keys on the literal host so a
    deliberately-declared subdomain root (``twip.kineticist.com`` under an existing
    ``kineticist.com``) is treated as a distinct, unseeded host, not folded into
    its parent domain. Root-scoped (``parent__isnull``) because only a root is a
    valid match target; a host illegitimately held by a child (a ``clean()``
    bypass) is handled defensively by :func:`_ensure_root_domains`, not matched
    here. Distinct by pk — one root may own several of the hosts.
    """
    from apps.citation.models import CitationSourceRootDomain

    rows = CitationSourceRootDomain.objects.filter(
        host__in=list(hosts), source__parent__isnull=True
    ).select_related("source")
    return list({row.source_id: row.source for row in rows}.values())


def _spans_two_roots_warning(name: str, host_roots: Sequence[CitationSource]) -> str:
    """The warning for a node whose recognition hosts span >1 existing root.

    Such a node skips whole at apply — picking one owner and minting the others
    would trip the ``host`` ``unique`` and wedge the queue. Names each owning root
    (the merge backlog until citation gardening ships). Shared by the apply-path
    warn-skip (:func:`ensure_root_source`) and the dry-run preview
    (:func:`detect_host_collision`) so the two channels never diverge.
    """
    owners = ", ".join(sorted(repr(r.name) for r in host_roots))
    return (
        f"Citation source {name!r} declares recognition hosts already owned "
        f"by {len(host_roots)} different roots ({owners}); skipped the node "
        f"(no writes) to avoid a domain collision. Resolve the duplicate "
        f"roots first."
    )


def _ensure_root_domains(
    source: CitationSource, hosts: Sequence[Host], *, warnings: list[str], actor: Actor
) -> None:
    """Additively mint a recognition domain on ``source`` for each unowned host.

    Each host is resolved against **every** existing owner (not just ``source``,
    and not root-scoped): a host ``source`` already owns is a no-op; a host owned
    by a *different* source warns and is skipped — never minted-over, so the
    ``host`` ``unique`` cannot trip and wedge the patch queue (honoring the
    module's "a collision is a warning, never a failure" contract). This is the
    backstop for a host the root-scoped :func:`_roots_owning_hosts` couldn't see
    — e.g. one a child illegitimately holds. Otherwise the host is ``full_clean``ed
    (firing the root-only/normalization guards) and saved.
    """
    from apps.citation.models import CitationSourceRootDomain

    for host in hosts:
        owner = (
            CitationSourceRootDomain.objects.filter(host=host)
            .select_related("source")
            .first()
        )
        if owner is not None:
            if owner.source_id != source.pk:
                warnings.append(
                    f"Recognition host {host!r} is already owned by "
                    f"{owner.source.name!r}; not minted on {source.name!r}."
                )
            continue
        domain = CitationSourceRootDomain(
            source=source, host=host, created_by=actor, updated_by=actor
        )
        domain.full_clean()
        domain.save()


# ---------------------------------------------------------------------------
# Read-phase validation + additive get-or-create
# ---------------------------------------------------------------------------


def validate_root_source(node: SourceNode) -> None:
    """Field-validate a patch ``sources:`` node in memory (no writes).

    Builds the ``CitationSource``, its ``CitationSourceLink`` rows and its
    ``CitationSourceRootDomain`` recognition hosts and runs ``full_clean`` on them
    with **DB-uniqueness off** — a node that legitimately matches an existing row
    (the additive get-or-create's "found" case) must not be rejected, and an
    in-memory link/domain's required FK is unset. Catches bad ``source_type``,
    out-of-range dates, invalid ``identifier_key``, malformed URL, invalid
    ``link_type``, duplicate declared link URLs, and a recognition host that isn't
    a DNS name or is a bare public suffix. The host set is the unified
    ``homepage ∪ domains`` set, so a bad **homepage** host fails here at
    ``--dry-run`` rather than crashing mid-apply at mint. Validating through the
    model's ``clean()`` keeps the host guard single-sourced (no forked predicate
    check). Raises :class:`django.core.exceptions.ValidationError`; the patch
    adapter maps it to a ``PatchError`` (so it surfaces at ``--dry-run`` before
    shipping).
    """
    from django.core.exceptions import ValidationError

    from apps.citation.models import (
        CitationSource,
        CitationSourceLink,
        CitationSourceRootDomain,
    )

    source = CitationSource(**_source_fields(node))
    source.full_clean(validate_unique=False)

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
        obj.full_clean(exclude=["citation_source"], validate_unique=False)

    for host in _declared_recognition_hosts(node):
        domain = CitationSourceRootDomain(host=host)
        domain.full_clean(exclude=["source"], validate_unique=False)


def detect_host_collision(node: SourceNode) -> str | None:
    """Committed-state recognition-host collision for one node, or ``None``.

    The dry-run preview of the whole-node skip :func:`ensure_root_source` would
    warn on at apply: a pure :func:`_roots_owning_hosts` read returning the
    spans-two-roots warning when the node's recognition hosts are owned by >1
    distinct root. An author validating against the dev DB sees the skip before
    publishing instead of only at live apply.

    **Committed state only — never a write simulation.** This deliberately does
    *not* account for a root an earlier node in the same plan will create: that
    would mean predicting the plan's own unwritten mutations (the
    ``_apply_dry_run`` carve-out pathology). A host that would attach to such a
    not-yet-created root won't flag here, and that false negative is accepted —
    the apply-time warn-skip stays the backstop. Keeping it a plain ``SELECT`` is
    what keeps this a preview, not a simulator. Returns the warning string (the
    apply path appends the identical one via :func:`_spans_two_roots_warning`) so
    the caller decides the channel; emits no ``PatchError`` (a collision is a
    state conflict, not a malformed patch).
    """
    host_roots = _roots_owning_hosts(_declared_recognition_hosts(node))
    if len(host_roots) > 1:
        return _spans_two_roots_warning(node["name"], host_roots)
    return None


def ensure_root_source(
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
    recognition_hosts = _declared_recognition_hosts(node)

    # Resolve by recognition host first; host identity wins over the name key.
    host_roots = _roots_owning_hosts(recognition_hosts)
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
        _ensure_root_domains(obj, recognition_hosts, warnings=warnings, actor=actor)
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

    # Additive links: create a missing URL, warn on a divergent same-URL link.
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
                f"Citation source {name!r} link {url!r} already exists with a "
                f"different type/label; left unchanged."
            )
    _ensure_root_domains(obj, recognition_hosts, warnings=warnings, actor=actor)
    return SourceUpsertResult(source_created=False, links_created=links_created)
