"""Catalog-free resolution primitives.

The shared kernel between *rank*
(:func:`apps.provenance.claim_ranking_in_db.ranked_claims`) and the per-shape
desired/diff/write logic — the layer-2 winner-pick.

Deliberately catalog-free — it imports only provenance and names no concrete
catalog model — so it can move wholesale to ``apps.provenance.resolution``. An
import-linter contract pins that boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterable

    from apps.provenance.models import Claim

type Winners[Subject: Hashable, Group: Hashable] = dict[Subject, dict[Group, "Claim"]]
"""Winning claim per ``(subject, group)`` — the first claim seen for each group
key within each subject, which is the highest-ranked one.  Both keys are
``Hashable`` because they index nested dicts."""


def pick_winners[Subject: Hashable, Group: Hashable](
    ranked: Iterable[Claim],
    subject: Callable[[Claim], Subject],
    group: Callable[[Claim], Group],
) -> Winners[Subject, Group]:
    """First (highest-ranked) claim per ``(subject, group)``.

    Folds a :func:`ranked_claims` queryset — already ordered so the first row
    per group is the winner — into a two-level map.  ``setdefault`` keeps the
    first claim seen for each group key, so a later (lower-ranked) claim for the
    same key is dropped.

    *subject* and *group* extract the keys from each claim — group on
    ``claim_key`` for membership sets (see :func:`pick_member_winners`) or on
    ``field_name`` for scalar registers, subject usually ``object_id`` but
    occasionally a composite key.
    """
    winners: Winners[Subject, Group] = {}
    for claim in ranked:
        winners.setdefault(subject(claim), {}).setdefault(group(claim), claim)
    return winners


def pick_member_winners(ranked: Iterable[Claim]) -> Winners[int, str]:
    """Membership winner-pick: one winner per ``claim_key`` per entity.

    Subject is the entity ``object_id``, group is the ``claim_key`` — a thin
    partial application of :func:`pick_winners` for the common case.
    """
    return pick_winners(ranked, lambda c: c.object_id, lambda c: c.claim_key)
