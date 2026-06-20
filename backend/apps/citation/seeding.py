"""Get-or-create citation sources for the data-patch ``sources:`` block.

The patch path (``apps.claim_ingest``) is the only caller. It is flat
(roots only) and **additive-only**: ``ensure_root_source`` creates a missing
source or backfills a missing link, but never overwrites an existing row or
link. A collision is a warning, never a failure — so a user-created source
can't wedge the patch queue. See ``docs/DataPatches.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict
from urllib.parse import urlparse

from apps.citation.hosts import Host, normalize_host
from apps.citation.seed_data.types import SeedLink, SeedSource

if TYPE_CHECKING:
    from apps.citation.models import CitationSource


class SourceFields(TypedDict):
    """The model-column subset of a seed/patch node — no parent, links or children.

    This is ``SeedSource`` minus its ``links``/``children`` keys: the exact set
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
# Shared leaf primitives (used by both the seed walk and the patch path)
# ---------------------------------------------------------------------------


class SourceMatch(NamedTuple):
    """The result of a soft-natural-key lookup: the first match and the count.

    ``match_count`` can exceed 1 on the ``(name, source_type)`` path (the caller
    warns and operates on ``source``); it is 0/1 on the unique ``isbn`` path.
    (Not named ``count`` — that would shadow ``tuple.count``.)
    """

    source: CitationSource | None
    match_count: int


def _source_fields(node: SeedSource) -> SourceFields:
    """Project a seed/patch node onto its model columns (drop parent/links/children).

    Built key-by-key rather than by comprehension so each value keeps its column
    type: ``SeedSource.items()`` erases to ``object``, but copying a known key
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

    The ``(name, source_type)`` match is root-scoped because the patch path
    creates *roots*: a same-named child (one a ``cite:`` minted, say) must not
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
        name=fields["name"], source_type=fields["source_type"], parent__isnull=True
    )
    return SourceMatch(qs.first(), qs.count())


def _create_source(
    fields: SourceFields, *, parent: CitationSource | None = None
) -> CitationSource:
    """Validate + save a new ``CitationSource`` under ``parent`` (default root)."""
    from apps.citation.models import CitationSource

    obj = CitationSource(**fields, parent=parent)
    obj.full_clean()
    obj.save()
    return obj


def _create_link(source: CitationSource, link: SeedLink) -> None:
    """Validate + save a single ``CitationSourceLink`` on ``source``."""
    from apps.citation.models import CitationSourceLink

    obj = CitationSourceLink(
        citation_source=source,
        url=link["url"],
        label=link.get("label", ""),
        link_type=link["link_type"],
    )
    obj.full_clean()
    obj.save()


def _declared_homepage_hosts(links: Sequence[SeedLink]) -> list[Host]:
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


def _roots_owning_hosts(hosts: Sequence[Host]) -> list[CitationSource]:
    """The distinct **root** sources that already own any of the given hosts.

    Exact-host lookup against ``CitationSourceRootDomain`` — **never** the
    longest-suffix matcher recognition uses. Dedup keys on the literal host so a
    deliberately-seeded subdomain root (``twip.kineticist.com`` under an existing
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


def _ensure_root_domains(
    source: CitationSource, hosts: Sequence[Host], *, warnings: list[str]
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
        domain = CitationSourceRootDomain(source=source, host=host)
        domain.full_clean()
        domain.save()


# ---------------------------------------------------------------------------
# Data-patch path: read-phase validation + additive get-or-create
# ---------------------------------------------------------------------------


def validate_root_source(node: SeedSource) -> None:
    """Field-validate a patch ``sources:`` node in memory (no writes).

    Builds the ``CitationSource`` and its ``CitationSourceLink`` rows and runs
    ``full_clean`` on them with **DB-uniqueness off** — a node that legitimately
    matches an existing row (the additive get-or-create's "found" case) must not
    be rejected, and an in-memory link's required FK is unset. Catches bad
    ``source_type``, out-of-range dates, invalid ``identifier_key``, malformed
    URL, invalid ``link_type``, and duplicate declared link URLs. Raises
    :class:`django.core.exceptions.ValidationError`; the patch adapter maps it to
    a ``PatchError`` (so it surfaces at ``--dry-run`` before shipping).
    """
    from django.core.exceptions import ValidationError

    from apps.citation.models import CitationSource, CitationSourceLink

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


def ensure_root_source(
    node: SeedSource,
    *,
    warnings: list[str],
) -> SourceUpsertResult:
    """Additively get-or-create a flat (root) citation source. Never overwrites.

    Resolution order, host before name:

    1. **By recognition host.** Resolve the node's declared ``homepage`` hosts to
       the roots that already own them (exact host, not suffix). Hosts owned by
       **>1 distinct root** → warn and **skip the node, no writes** (picking one
       and minting the other would trip the ``host`` ``unique`` and wedge the
       queue). Exactly **one** owning root → that's the match (host wins even if
       a differently-named root shares the ``(name, source_type)`` — the re-seed-
       under-a-new-name case).
    2. **By soft natural key.** No host match → fall back to ``isbn`` /
       ``(name, source_type)`` (root-scoped so a same-named child can't shadow
       the root), so a same-named root merely gaining a *new* homepage host is
       found, not duplicated. On >1 match, operate on the first and warn. Still
       absent → create the source + all its declared links.

    On the matched-or-created root, additively ensure each declared link (create
    a missing URL, no-op an identical one, warn on a same-URL/different-type one)
    and mint a ``CitationSourceRootDomain`` for every declared homepage host it
    doesn't already own. Never raises on a collision; the caller tallies counts.
    """
    fields = _source_fields(node)
    name = fields["name"]
    source_type = fields["source_type"]
    links = node.get("links", [])
    homepage_hosts = _declared_homepage_hosts(links)

    # Resolve by recognition host first; host identity wins over the name key.
    host_roots = _roots_owning_hosts(homepage_hosts)
    if len(host_roots) > 1:
        warnings.append(
            f"Citation source {name!r} declares homepage hosts already owned by "
            f"{len(host_roots)} different roots; skipped the node (no writes) to "
            f"avoid a domain collision. Resolve the duplicate roots first."
        )
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
        obj = _create_source(fields)
        for link in links:
            _create_link(obj, link)
        _ensure_root_domains(obj, homepage_hosts, warnings=warnings)
        return SourceUpsertResult(source_created=True, links_created=len(links))

    # Found: never overwrite the row; warn on any declared-field divergence.
    # A host match under a different name is expected (re-seed under a new name),
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
            _create_link(obj, link)
            links_created += 1
        elif current.link_type != link["link_type"] or current.label != link.get(
            "label", ""
        ):
            warnings.append(
                f"Citation source {name!r} link {url!r} already exists with a "
                f"different type/label; left unchanged."
            )
    _ensure_root_domains(obj, homepage_hosts, warnings=warnings)
    return SourceUpsertResult(source_created=False, links_created=links_created)
