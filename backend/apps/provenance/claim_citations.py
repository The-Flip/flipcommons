"""Serializing the citations that back a claim.

A claim carries evidence two ways: instances *attached* to it through the
``ClaimCitationInstance`` join, and instances referenced *inline* by
``[[cite:id:N]]`` markers inside a markdown value. The batch lookup and the
per-instance serializer cover both, so a claim's evidence serializes the same
way wherever it is rendered.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

from apps.citation.deep_links import deep_linked_url
from apps.citation.models import CitationInstance
from apps.core.wikilinks import get_link_type, get_patterns

from .helpers import citation_instances
from .models import Claim
from .schemas import CitationLinkSchema, ClaimCitationSchema


class InlineCitationLookup:
    """Citation instances resolved from ``[[cite:id:N]]`` markers, keyed by pk.

    Built once per response by :func:`resolve_inline_citations`, so per-claim
    citation building does no DB work.
    """

    __slots__ = ("_instances",)

    def __init__(self) -> None:
        self._instances: dict[int, CitationInstance] = {}

    def add(self, instance: CitationInstance) -> None:
        assert instance.pk is not None
        self._instances[instance.pk] = instance

    def get(self, pk: int) -> CitationInstance | None:
        return self._instances.get(pk)


def _cite_storage_pattern() -> re.Pattern[str] | None:
    """The compiled ``[[cite:id:N]]`` pattern, or None when the ``cite``
    link type isn't registered (cleared-registry tests)."""
    link_type = get_link_type("cite")
    if link_type is None:
        return None
    return get_patterns(link_type)["storage"]


def inline_cite_pks(value: object) -> list[int]:
    """Citation-instance pks referenced by ``[[cite:id:N]]`` markers in
    *value*, in document order, deduped keeping the first occurrence."""
    if not isinstance(value, str) or not value:
        return []
    pattern = _cite_storage_pattern()
    if pattern is None:
        return []
    seen: set[int] = set()
    pks: list[int] = []
    for match in pattern.finditer(value):
        pk = int(match.group(1))
        if pk not in seen:
            seen.add(pk)
            pks.append(pk)
    return pks


def resolve_inline_citations(values: Iterable[object]) -> InlineCitationLookup:
    """Batch-load every citation instance referenced inline across *values*.

    One query (plus the links prefetch), independent of how many values are
    passed, so callers rendering many claim values stay query-bounded.
    """
    pks: set[int] = set()
    for value in values:
        pks.update(inline_cite_pks(value))
    lookup = InlineCitationLookup()
    if not pks:
        return lookup
    instances = (
        CitationInstance.objects.filter(pk__in=pks)
        # The parent ride-along feeds deep_linked_url (scheme lookup via the
        # root's identifier_key) without a per-cite query.
        .select_related("citation_source", "citation_source__parent")
        .prefetch_related("citation_source__links")
    )
    for instance in instances:
        lookup.add(instance)
    return lookup


def citation_schema(inst: CitationInstance, *, slug: str | None) -> ClaimCitationSchema:
    """Serialize one citation instance for a claim."""
    source = inst.citation_source
    assert inst.pk is not None
    # The parent root, so a child (a periodical issue, a book volume) renders in
    # context — "Vol. 2" alone is ambiguous without the work it belongs to.
    # None on a root; select_related on both instance paths (the inline lookup
    # and the attached-evidence prefetch), so it costs no query.
    root = source.parent
    return ClaimCitationSchema(
        id=inst.pk,
        source_name=source.name,
        root_name=root.name if root is not None else None,
        source_type=source.source_type,
        author=source.author,
        year=source.year,
        locator=inst.locator,
        quote=inst.quote,
        slug=slug,
        links=[
            CitationLinkSchema(
                url=deep_linked_url(source, inst.locator, link.url),
                link_type=link.link_type,
                display_name=link.display_name,
            )
            for link in source.links.all()
        ],
    )


class ClaimCitations(NamedTuple):
    """A claim's citations, plus the inline pks consumed building them.

    Callers that also need "which markers does this value carry" get them
    here rather than re-scanning the value — the regex pass over a long
    markdown field is the expensive part.
    """

    schemas: list[ClaimCitationSchema]
    inline_pks: list[int]


def claim_citation_schemas(
    claim: Claim, inline: InlineCitationLookup
) -> ClaimCitations:
    """Every citation backing *claim*'s own value.

    Attached (join-row) evidence comes first — *claim* must have been loaded
    with its citation instances prefetched — then the ``[[cite:id:N]]`` markers
    in the claim's value in document order. A marker whose instance row is gone
    is skipped rather than raising: a broken link degrades to no citation.
    """
    schemas = [citation_schema(inst, slug=None) for inst in citation_instances(claim)]
    pks = inline_cite_pks(claim.value)
    for pk in pks:
        inst = inline.get(pk)
        if inst is not None:
            schemas.append(citation_schema(inst, slug=inst.slug))
    return ClaimCitations(schemas, pks)
