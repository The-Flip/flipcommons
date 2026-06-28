"""Canonical claim winner-pick — how a Source/User wins a ``claim_key``.

Ranking claims is a Claim-level concern, so it lives here in provenance (the
layer that owns :class:`~apps.provenance.models.Claim`) and is shared by every
``ClaimControlledModel`` consumer — catalog's resolvers and provenance's own
prefetch/history helpers — so the rule cannot drift.

The single public entry point is :func:`ranked_claims`: it filters to eligible
claims, annotates ``effective_priority`` and applies the deterministic tiebreak
order in one call, so a consumer cannot accidentally forget the tail and pick an
arbitrary winner.  Iterate the result and keep the first claim per grouping key::

    for claim in ranked_claims(qs, "object_id", "claim_key"):
        winners.setdefault((claim.object_id, claim.claim_key), claim)

The order ends in ``-pk`` so claims that tie on priority and ``created_at``
(real, not hypothetical: one transaction's bulk insert shares
``db_default=Now()``) resolve deterministically to the highest pk = the last
write, instead of undefined database row order.

A guard test (``apps/provenance/tests/test_ranking_is_canonical.py``) fails if
any module re-spells the annotation or the order, or reaches past
:func:`ranked_claims` to the private primitives below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import F

from apps.actors.models import ActorResolutionStatus

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.provenance.models import Claim

# Highest effective_priority, then newest created_at, then highest pk (= last
# write) — a total, deterministic order.  Private: callers go through
# ``ranked_claims`` so the tail can never be omitted.
#
# Priority dominates; recency is only a tiebreak — a higher-priority source beats
# a more-recent lower-priority claim. This is a generalized LWW-Register (any
# total order on writes), NOT wall-clock LWW; plain "last write wins" is the
# degenerate case where all priorities are equal. Do not reorder these so recency
# leads — that would silently let a newer low-priority edit override a curated
# high-priority source.
_WINNER_ORDER: tuple[str, ...] = ("-effective_priority", "-created_at", "-pk")


def _annotate_priority(qs: QuerySet[Claim]) -> QuerySet[Claim]:
    """Filter to active claims from non-suppressed actors and annotate effective_priority.

    Private — :func:`ranked_claims` is the only winner-pick entry point, so the
    annotation and the order stay welded together.

    Reads resolution inputs off ``Claim.actor`` (one uniform column per actor
    type): ``actor.resolution_status`` (suppressed actors never win — the kill
    switch migrated from ``Source.is_enabled``) and ``actor.priority`` (replaces
    the ``Source.priority`` / ``User.priority`` fork). The backing one-to-ones are
    select_related so downstream attribution display stays a single query.
    """
    return (
        qs.filter(is_active=True)
        .exclude(actor__resolution_status=ActorResolutionStatus.SUPPRESSED)
        .select_related("actor__user", "actor__source")
        .annotate(effective_priority=F("actor__priority"))
    )


def ranked_claims(qs: QuerySet[Claim], *group_keys: str) -> QuerySet[Claim]:
    """Eligible claims, ordered so the first per grouping key is the winner.

    The single SQL winner-pick: filters to active claims from enabled sources,
    annotates ``effective_priority`` and orders by *group_keys* then the
    priority/recency/pk tiebreak.  Pass the grouping columns the caller dedups on
    (e.g. ``"object_id", "claim_key"``); they sort first so each group is
    contiguous, ranked within.  Extra ``.filter()`` / ``.select_related()`` may
    be chained onto the result — ordering survives.
    """
    return _annotate_priority(qs).order_by(*group_keys, *_WINNER_ORDER)
