"""Shared helpers for working with provenance claims."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from django.db.models import Prefetch, QuerySet

from apps.actors.models import Actor
from apps.citation.models import CitationInstance

from .attribution import actor_user, source_backing
from .claim_ranking_in_db import ranked_claims
from .display import FieldValue, claim_value, resolve_display_context
from .models import ChangeSet, Claim, ClaimControlledModel
from .schemas import (
    ClaimAttributionSchema,
    ClaimAuthorSchema,
    ClaimSchema,
    ClaimSourceAuthorSchema,
    ClaimUserAuthorSchema,
)


def actor_author(actor: Actor) -> ClaimAuthorSchema:
    """Build the tagged author for an Actor, via its backing record.

    The schema-producing counterpart to ``attribution.source_backing`` /
    ``actor_user``, which it delegates to so the field reads are typed
    (``User.username`` / ``Source.name``) rather than ``getattr``-``Any``.
    Callers must ``select_related`` the backing one-to-one so this is a column
    read. An orphaned actor (backing row deleted) renders a ``[deleted …]``
    placeholder of the correct chip type — non-crashing; the full
    ``[deleted <kind>]`` chip (badge/link) is deferred.
    """
    if (user := actor_user(actor)) is not None:
        return ClaimUserAuthorSchema(username=user.username)
    if (source := source_backing(actor)) is not None:
        return ClaimSourceAuthorSchema(name=source.name)
    # Backing row gone (orphaned actor): fall back to a placeholder of the chip
    # type that backing_model still names.
    if actor.backing_model == "user":
        return ClaimUserAuthorSchema(username="[deleted user]")
    return ClaimSourceAuthorSchema(name=f"[deleted {actor.backing_model}]")


def claim_author(claim: Claim) -> ClaimAuthorSchema:
    """Build the tagged author for a Claim, via its actor."""
    assert claim.actor is not None
    return actor_author(claim.actor)


def changeset_author(cs: ChangeSet) -> ClaimAuthorSchema:
    """Build the tagged author for a ChangeSet, via its actor."""
    assert cs.actor is not None
    return actor_author(cs.actor)


def citation_instances_prefetch() -> Prefetch[str, QuerySet[CitationInstance], str]:
    """Prefetch citation instances (+ source links) onto each claim.

    Traverses ``Claim.citation_instances`` — the M2M over the
    ``ClaimCitationInstance`` join — so only instances attached as supporting
    evidence appear; inline ``[[cite:...]]`` instances carry no join rows.
    Lands them on ``prefetched_citation_instances`` — the attribute
    :func:`citation_instances` reads — so callers that build field-change
    citations (edit history, changeset detail) avoid a per-claim query.
    """
    return Prefetch(
        "citation_instances",
        # The parent ride-along feeds deep_linked_url (scheme lookup via the
        # root's identifier_key) without a per-instance query.
        queryset=CitationInstance.objects.select_related(
            "citation_source", "citation_source__parent"
        ).prefetch_related("citation_source__links"),
        to_attr="prefetched_citation_instances",
    )


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
        # ranked_claims already select_relates the claim's actor backings (for
        # claim_author); changeset__actor__user covers the per-claim changeset
        # note and the changeset author the evidence panel reads.
        ranked_claims(Claim.objects.all(), "claim_key")
        .select_related("changeset__actor__user")
        .prefetch_related(citation_instances_prefetch())
    )
    if field_names is not None:
        queryset = queryset.filter(field_name__in=list(field_names))
    return Prefetch("claims", queryset=queryset, to_attr=to_attr)


def active_claims(entity: ClaimControlledModel) -> list[Claim]:
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


def build_sources(
    model: type[ClaimControlledModel], claims: Iterable[Claim]
) -> list[ClaimSchema]:
    """Serialize pre-fetched active claims into the sources list format.

    ``model`` is the subject entity's class — all claims belong to one entity,
    so it is uniform and the caller supplies it (do not hop
    ``claim.content_type`` per claim: ``claims_prefetch`` does not
    ``select_related`` it, so that would be an N+1).

    Claims should be ordered by claim_key, -priority, -created_at. The first
    claim seen per claim_key is marked as the winner.

    The iterable is materialized to a list internally so FK labels and
    wikilink authoring keys can be resolved in a single batched pass before
    the per-claim loop.
    """
    claims = list(claims)
    ctx = resolve_display_context(
        FieldValue(c.field_name, c.value, model) for c in claims
    )
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
                value=claim_value(model, claim.field_name, claim.value, ctx),
                is_winner=is_winner,
                changeset_note=claim.changeset.note if claim.changeset else None,
            )
        )
    sources.sort(key=lambda c: c.attribution.created_at, reverse=True)
    return sources
