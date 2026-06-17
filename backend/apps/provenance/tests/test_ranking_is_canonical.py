"""Guard: the claim winner-pick is defined and entered in exactly one place.

Every ``ClaimControlledModel`` ranks claims the same way — through
:func:`apps.provenance.claim_ranking_in_db.ranked_claims`.  These tests fail if
any other module re-spells the priority annotation, re-spells the ``order_by``
tail, or reaches past ``ranked_claims`` to the private primitives.  That is how
the ``-pk`` tiebreak silently drifted before: catalog's MachineModel resolvers
had it, while the generic-entity resolver, the relationship/media resolvers and
the provenance prefetch/history helpers did not.  A source
scan is coarse but catches the one thing that matters — a second, divergent copy
of the rule, or a consumer that orders the winner-pick itself (and could forget
the tail).
"""

from __future__ import annotations

from pathlib import Path

import apps.provenance.claim_ranking_in_db as ranking

_CANONICAL = Path(ranking.__file__).resolve()
_APPS_DIR = _CANONICAL.parents[1]  # .../backend/apps


def _production_sources() -> list[Path]:
    """Every non-test, non-migration app module except the canonical one."""
    return [
        path
        for path in _APPS_DIR.rglob("*.py")
        if "migrations" not in path.parts
        and "tests" not in path.parts
        and path.resolve() != _CANONICAL
    ]


def _offenders(needle: str) -> list[str]:
    return [str(p) for p in _production_sources() if needle in p.read_text()]


def test_priority_annotation_defined_only_in_ranking() -> None:
    """The ``effective_priority`` annotation exists only in the canonical module."""
    offenders = _offenders("effective_priority=Case")
    assert not offenders, (
        f"Re-implemented the priority annotation outside {ranking.__name__}: "
        f"{offenders}. Use ranked_claims() instead."
    )


def test_winner_order_spelled_only_in_ranking() -> None:
    """The ``-effective_priority`` order key is only spelled in the canonical module."""
    offenders = _offenders('"-effective_priority"')
    assert not offenders, (
        f"Hard-coded the winner-pick order outside {ranking.__name__}: "
        f"{offenders}. Use ranked_claims() instead."
    )


def test_winner_pick_entered_only_through_ranked_claims() -> None:
    """No consumer orders the winner-pick itself — closes the under-ordering gap.

    ``ranked_claims`` welds the annotation to the tiebreak order, so a consumer
    that goes through it cannot forget the tail and pick an arbitrary winner.
    A consumer that instead calls the private ``annotate_priority`` and orders by
    hand *could* — so that primitive must stay inside the canonical module.
    """
    offenders = _offenders("annotate_priority")
    assert not offenders, (
        f"Called the private annotate_priority outside {ranking.__name__}: "
        f"{offenders}. Use ranked_claims() so the tiebreak order can't be dropped."
    )
