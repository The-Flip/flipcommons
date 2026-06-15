"""Pure, ORM-free definition of the claim winner-pick.

Extracts the *definition* of claim ranking — eligibility, effective priority
and the recency tiebreak — from the SQL winner-pick
:func:`apps.provenance.claim_ranking_in_db.ranked_claims` into plain functions
over an in-memory claim.  Each rule is documented on the function that owns it.

Why two forms?  Catalog-scale resolve keeps its DB-side ``order_by`` over the
whole claim table (:func:`apps.catalog.resolve.resolve_machine_models`) —
pushing that through Python would be a needless regression.  But the patch
front end must rank a *tiny* set of claims that includes ones not yet written
to the database (pending claims emitted earlier in the same patch), which SQL
can't order because they do not exist in any table.

So the rule lives in two execution paths — the SQL winner-pick
:func:`apps.provenance.claim_ranking_in_db.ranked_claims` that every resolver
uses, and the pure functions here — pinned to agree by an equivalence test
(``tests/test_claim_ranking_in_memory.py``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import NamedTuple, Protocol

# A pending claim has no ``created_at`` yet; it ranks as the newest possible
# assertion.  ``datetime.max`` is well beyond any real ``created_at``, and is
# made tz-aware to compare against the aware timestamps Django stores
# (``USE_TZ=True``).
_PENDING_RECENCY = datetime.max.replace(tzinfo=UTC)


class SourceLike(Protocol):
    """A claim's source, as the winner-pick sees it (read-only)."""

    @property
    def priority(self) -> int: ...

    @property
    def is_enabled(self) -> bool: ...


class UserLike(Protocol):
    """A claim's authoring user, as the winner-pick sees it (read-only)."""

    @property
    def priority(self) -> int: ...


class ClaimToRank(Protocol):
    """The minimal claim shape needed by the claim-ranking algorithm.

    A claim projected onto just the fields ranking needs — it omits the
    asserted payload (``value``, ``field_name``, …).  Satisfied structurally by
    :class:`apps.provenance.models.Claim` (with ``source``/``user``
    select_related) and by the pending in-memory claims the patch front end will
    accumulate.  ``created_at`` and ``pk`` are ``None`` for a pending claim that
    has not been written yet; such a claim sorts as newest.
    """

    @property
    def is_active(self) -> bool: ...

    @property
    def claim_key(self) -> str: ...

    @property
    def created_at(self) -> datetime | None: ...

    @property
    def pk(self) -> int | None: ...

    @property
    def source(self) -> SourceLike | None: ...

    @property
    def user(self) -> UserLike | None: ...


def is_eligible(claim: ClaimToRank) -> bool:
    """Whether *claim* participates in resolution.

    Mirrors ``ranked_claims``'s eligibility filter (``filter(is_active=True)`` +
    ``exclude(source__is_enabled=False)``): an inactive claim, or one from a
    disabled source, is dropped.  A user claim (``source is None``) is never
    dropped on the source check, matching the SQL ``exclude`` over the
    nullable join.
    """
    if not claim.is_active:
        return False
    return claim.source is None or claim.source.is_enabled


def effective_priority(claim: ClaimToRank) -> int:
    """The claim's resolution weight; higher wins.

    Mirrors the priority ``Case/When`` in ``ranked_claims``: source priority if
    sourced, else user priority if user-authored, else ``0``.
    """
    if claim.source is not None:
        return claim.source.priority
    if claim.user is not None:
        return claim.user.priority
    return 0


class WinnerRank(NamedTuple):
    """How a claim ranks within its ``claim_key`` group; larger wins.

    Field order matters: tuple comparison weighs ``priority`` first, then
    ``recency``, then ``tiebreak`` — reproducing the order
    :func:`apps.provenance.claim_ranking_in_db.ranked_claims` applies.  The
    ``pk`` tiebreak makes the order total, so claims that share priority and
    ``created_at`` resolve deterministically to the highest pk = the last write,
    instead of SQL's
    undefined row order.
    """

    priority: int
    recency: datetime
    # Claim pk as float (real pks are « 2**53, so the cast is exact); +inf for a
    # pending claim.  Only ever decides between committed claims of equal
    # priority and ``created_at`` — a pending claim already outranks every
    # committed one on ``recency`` before ``tiebreak`` is consulted.
    tiebreak: float


def winner_sort_key(claim: ClaimToRank) -> WinnerRank:
    """Rank *claim* for the winner-pick (see :class:`WinnerRank`).

    ``recency`` is the ``created_at`` datetime — compared directly, not via a
    float timestamp, so the tiebreak stays bit-for-bit aligned with the SQL
    ordering down to the microsecond.  A pending claim (no ``created_at``/``pk``)
    gets the newest sentinels (``_PENDING_RECENCY``, ``+inf``) so it sorts last
    -written.
    """
    return WinnerRank(
        priority=effective_priority(claim),
        recency=claim.created_at or _PENDING_RECENCY,
        tiebreak=float(claim.pk) if claim.pk is not None else float("inf"),
    )


def pick_winners[C: ClaimToRank](claims: Iterable[C]) -> dict[str, C]:
    """Pick the winning claim per ``claim_key`` from a flat iterable.

    Drops ineligible claims, orders the rest exactly as the SQL
    :func:`~apps.provenance.claim_ranking_in_db.ranked_claims` would, then keeps
    the first per ``claim_key`` — the in-memory mirror of the first-wins loop in
    :func:`apps.catalog.resolve.resolve_model`.  Returns ``{claim_key: winner}``.

    **Precondition** — at most one *active* claim per (``claim_key``, author),
    the invariant the DB maintains (``assert_claim`` deactivates a prior claim
    from the same author).  Committed claims satisfy it already; the environment
    must apply the same last-emitted-wins dedup to pending claims before ranking.
    On an exact tie the first input element wins, so two *un-deduped* pending
    writes to one cell would resolve oldest-first — the opposite of the claims
    system — which is why that dedup is the caller's job, not this function's.
    """
    ordered = sorted(
        (claim for claim in claims if is_eligible(claim)),
        key=winner_sort_key,
        reverse=True,
    )
    winners: dict[str, C] = {}
    for claim in ordered:
        winners.setdefault(claim.claim_key, claim)
    return winners
