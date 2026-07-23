"""Building the per-entity Sources page model from active claims."""

from __future__ import annotations

from collections.abc import Iterable

from .claim_citations import claim_citation_schemas, resolve_inline_citations
from .display import FieldValue, claim_value, resolve_display_context
from .helpers import claim_author
from .models import Claim, ClaimControlledModel
from .parked_fields import HIDDEN_PARKED_FIELDS
from .schemas import ClaimAttributionSchema, ClaimSchema


def build_sources(
    model: type[ClaimControlledModel], claims: Iterable[Claim]
) -> list[ClaimSchema]:
    """Serialize pre-fetched active claims into the sources list format.

    ``model`` is the subject entity's class — all claims belong to one entity,
    so it is uniform and the caller supplies it rather than this hopping
    ``claim.content_type`` per claim, which is not joined and so would N+1.

    Claims must arrive ordered by claim_key, then rank, so the first claim seen
    per claim_key is its winner.

    ``claim_key`` is the slot: composite for a relationship member (one winner
    per related row), equal to ``field_name`` for a direct or ``extra_data``
    field (one winner per column). Those coincide with how the resolver groups
    for as long as a non-relationship claim's key stays canonical.

    Parked source fields (see :mod:`.parked_fields`) are dropped before
    anything else runs, so they cost no display resolution and take no
    reference number.

    The iterable is materialized to a list internally so FK labels, wikilink
    authoring keys and inline citations can each be resolved in a single
    batched pass before the per-claim loop.
    """
    claims = [c for c in claims if c.field_name not in HIDDEN_PARKED_FIELDS]
    ctx = resolve_display_context(
        FieldValue(c.field_name, c.value, model) for c in claims
    )
    inline = resolve_inline_citations(c.value for c in claims)

    claimed: set[str] = set()
    sources: list[ClaimSchema] = []
    for claim in claims:
        is_winner = claim.claim_key not in claimed
        claimed.add(claim.claim_key)
        sources.append(
            ClaimSchema(
                attribution=ClaimAttributionSchema(
                    author=claim_author(claim),
                    created_at=claim.created_at.isoformat(),
                ),
                field_name=claim.field_name,
                claim_key=claim.claim_key,
                value=claim_value(model, claim.field_name, claim.value, ctx),
                is_winner=is_winner,
                citations=claim_citation_schemas(claim, inline).schemas,
            )
        )
    return sources
