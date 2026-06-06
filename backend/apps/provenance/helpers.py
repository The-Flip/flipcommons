"""Shared helpers for working with provenance claims."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from django.db import models
from django.db.models import Case, F, IntegerField, Prefetch, QuerySet, Value, When

from .display import FieldValue, claim_value, resolve_labels
from .models import ChangeSet, CitationInstance, Claim
from .schemas import (
    ClaimAttributionSchema,
    ClaimAuthorSchema,
    ClaimSchema,
    ClaimSourceAuthorSchema,
    ClaimUserAuthorSchema,
)


def claim_author(claim: Claim) -> ClaimAuthorSchema:
    """Build the tagged author for a Claim. Exactly one FK is set (DB CHECK)."""
    if claim.user is not None:
        return ClaimUserAuthorSchema(username=claim.user.username)
    assert claim.source is not None
    return ClaimSourceAuthorSchema(name=claim.source.name)


def changeset_author(cs: ChangeSet) -> ClaimAuthorSchema:
    """Build the tagged author for a ChangeSet. Exactly one FK is set (DB CHECK)."""
    if cs.user is not None:
        return ClaimUserAuthorSchema(username=cs.user.username)
    assert cs.ingest_run is not None
    return ClaimSourceAuthorSchema(name=cs.ingest_run.source.name)


def claims_prefetch(
    to_attr: str = "active_claims",
    *,
    field_names: Iterable[str] | None = None,
) -> Prefetch[str, QuerySet[Claim], str]:
    """Return a Prefetch for active claims with priority annotation.

    Pass *field_names* to restrict the prefetch to specific claim fields (e.g.
    ``("description",)`` for a bulk dump that only needs description attribution),
    so it doesn't drag the whole claim table.
    """
    queryset = (
        Claim.objects.filter(is_active=True)
        .exclude(source__is_enabled=False)
        .select_related("source", "user", "changeset__user")
        .prefetch_related(
            Prefetch(
                "citation_instances",
                queryset=CitationInstance.objects.select_related(
                    "citation_source"
                ).prefetch_related("citation_source__links"),
                to_attr="prefetched_citation_instances",
            )
        )
        .annotate(
            effective_priority=Case(
                When(source__isnull=False, then=F("source__priority")),
                When(user__isnull=False, then=F("user__priority")),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("claim_key", "-effective_priority", "-created_at")
    )
    if field_names is not None:
        queryset = queryset.filter(field_name__in=list(field_names))
    return Prefetch("claims", queryset=queryset, to_attr=to_attr)


def active_claims(entity: models.Model) -> list[Claim]:
    """Return the list of active claims prefetched onto *entity*.

    Raises AssertionError if the queryset wasn't set up with
    ``claims_prefetch()``.
    """
    claims = getattr(entity, "active_claims", None)
    if claims is None:
        raise AssertionError(
            f"{type(entity).__name__} was not loaded via claims_prefetch()"
        )
    return cast(list[Claim], claims)


def citation_instances(claim: Claim) -> list[CitationInstance]:
    """Return the list of citation instances prefetched onto *claim*.

    Raises AssertionError if the claim wasn't loaded via ``claims_prefetch()``.
    """
    instances = getattr(claim, "prefetched_citation_instances", None)
    if instances is None:
        raise AssertionError(
            "Claim was not loaded via claims_prefetch(); "
            "prefetched_citation_instances is missing."
        )
    return cast(list[CitationInstance], instances)


def build_sources(claims: Iterable[Claim]) -> list[ClaimSchema]:
    """Serialize pre-fetched active claims into the sources list format.

    Claims should be ordered by claim_key, -priority, -created_at. The first
    claim seen per claim_key is marked as the winner.

    The iterable is materialized to a list internally so FK display labels can
    be resolved in a single batched pass before the per-claim loop.
    """
    claims = list(claims)
    labels = resolve_labels(FieldValue(c.field_name, c.value) for c in claims)
    winners: set[str] = set()
    sources: list[ClaimSchema] = []
    for claim in claims:
        is_winner = claim.claim_key not in winners
        if is_winner:
            winners.add(claim.claim_key)
        sources.append(
            ClaimSchema(
                attribution=ClaimAttributionSchema(
                    author=claim_author(claim),
                    created_at=claim.created_at.isoformat(),
                ),
                field_name=claim.field_name,
                value=claim_value(claim.field_name, claim.value, labels),
                citation=claim.citation,
                is_winner=is_winner,
                changeset_note=claim.changeset.note if claim.changeset else None,
            )
        )
    sources.sort(key=lambda c: c.attribution.created_at, reverse=True)
    return sources
