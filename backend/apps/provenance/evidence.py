"""Helpers for reader-facing cited edit evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from apps.actors.types import ActorId
from apps.citation.deep_links import deep_linked_url

from .attribution import actor_user
from .helpers import citation_instances
from .models import Claim
from .types import ChangeSetId


@dataclass(frozen=True)
class EvidenceLink:
    url: str
    label: str


@dataclass(frozen=True)
class CitedCitation:
    source_name: str
    source_type: str
    author: str
    year: int | None
    locator: str
    quote: str
    links: list[EvidenceLink]


@dataclass(frozen=True)
class CitedChangeset:
    id: ChangeSetId
    # The changeset's actor id — satisfies ChangeSetPolicyView for the
    # CHANGESET_UNDO capability check. ``user_username`` carries display.
    actor_id: ActorId
    user_username: str
    note: str
    created_at: str
    fields: list[str]
    citations: list[CitedCitation]


@dataclass
class _CitedChangesetBuilder:
    """Mutable scratch state while grouping citations per changeset."""

    id: ChangeSetId
    actor_id: ActorId
    user_username: str
    note: str
    created_at: str
    fields: list[str] = field(default_factory=list)
    field_set: set[str] = field(default_factory=set)
    citations: dict[tuple[int, str, str], CitedCitation] = field(default_factory=dict)


def build_cited_changesets(claims: Iterable[Claim]) -> list[CitedChangeset]:
    """Serialize active user changesets that have attached citation instances."""
    grouped: dict[int, _CitedChangesetBuilder] = {}

    for claim in claims:
        # Read authorship off ``claim.changeset.actor`` rather than the claim's
        # own actor. The two match by write-time convention but aren't a DB
        # invariant — revert flows can attach source-attributed claims to a user
        # changeset. The changeset's actor is the policy-relevant author; only
        # user-backed changesets surface here (source/ingest are skipped).
        changeset = claim.changeset
        author = actor_user(changeset.actor) if changeset is not None else None
        if changeset is None or author is None:
            continue

        claim_citations = citation_instances(claim)
        if not claim_citations:
            continue

        entry = grouped.get(changeset.pk)
        if entry is None:
            assert changeset.actor_id is not None
            entry = _CitedChangesetBuilder(
                id=changeset.pk,
                actor_id=changeset.actor_id,
                user_username=author.username,
                note=changeset.note,
                created_at=changeset.created_at.isoformat(),
            )
            grouped[changeset.pk] = entry

        if claim.field_name not in entry.field_set:
            entry.field_set.add(claim.field_name)
            entry.fields.append(claim.field_name)

        for citation in claim_citations:
            signature = (citation.citation_source_id, citation.locator, citation.quote)
            if signature in entry.citations:
                continue
            entry.citations[signature] = CitedCitation(
                source_name=citation.citation_source.name,
                source_type=citation.citation_source.source_type,
                author=citation.citation_source.author,
                year=citation.citation_source.year,
                locator=citation.locator,
                quote=citation.quote,
                links=[
                    EvidenceLink(
                        url=deep_linked_url(
                            citation.citation_source, citation.locator, link.url
                        ),
                        label=link.label,
                    )
                    for link in citation.citation_source.links.all()
                ],
            )

    result: list[CitedChangeset] = [
        CitedChangeset(
            id=entry.id,
            actor_id=entry.actor_id,
            user_username=entry.user_username,
            note=entry.note,
            created_at=entry.created_at,
            fields=entry.fields,
            citations=list(entry.citations.values()),
        )
        for entry in grouped.values()
    ]
    result.sort(key=lambda item: item.created_at, reverse=True)
    return result
