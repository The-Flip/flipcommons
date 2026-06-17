"""Guard: catalog liveness is defined and spelled in exactly one place.

"Is this entity live?" has two execution forms that must stay in lock-step — a
SQL ``Q`` (:func:`apps.core.models.active_status_q` / ``.active()``) and an
in-memory predicate (:func:`apps.core.models.is_live` /
:func:`apps.core.models.is_deleted`).  They agree *only* because ``EntityStatus``
is the closed domain ``{active, deleted}``: ``status IN (active, null)`` equals
``status != deleted`` precisely while no third member exists.

These tests fail the build if (a) ``EntityStatus`` gains a member without the
liveness definition being revisited, or (b) any module re-spells the rule by
hand — a literal ``status == "deleted"`` comparison, or a hand-built
``status__isnull`` liveness ``Q`` — instead of routing through the four
canonical entry points.  Re-spelling is exactly how the two forms silently
re-fork: a hand-written liveness ``Q`` that forgets the null clause, or a
``!= "deleted"`` that diverges once a third status exists.
"""

from __future__ import annotations

from apps.core.models import EntityStatus, is_deleted, is_live
from apps.core.tests._source_guard import offenders

# ---------------------------------------------------------------------------
# Closed-domain guard — the reason the SQL and predicate forms agree.
# ---------------------------------------------------------------------------


def test_entity_status_is_a_closed_two_member_domain() -> None:
    """``is_live``/``.active()`` agree only while the domain is {active, deleted}.

    ``active_status_q`` selects ``status IN (active, null)``; ``is_live`` returns
    ``status != deleted``.  They are equal *because* ``active`` and ``deleted``
    are the only non-null members.  Add ``ARCHIVED``/``DRAFT`` and they diverge
    (the Q excludes it, the predicate includes it) — at which point the liveness
    definition must be revisited, not silently inherited.
    """
    assert set(EntityStatus.values) == {"active", "deleted"}, (
        "EntityStatus gained/lost a member. Liveness (is_live / active_status_q) "
        "assumes the closed domain {active, deleted}; revisit both forms before "
        "changing the domain — see apps/core/models/mixins.py."
    )


# ---------------------------------------------------------------------------
# Pure-unit — pin the predicate definitions.
# ---------------------------------------------------------------------------


class TestIsLive:
    def test_active_is_live(self) -> None:
        assert is_live("active")

    def test_deleted_is_not_live(self) -> None:
        assert not is_live("deleted")

    def test_null_is_live(self) -> None:
        # Legacy ingest rows predate status claims; null reads as live, matching
        # the null-inclusive SQL active_status_q.
        assert is_live(None)


class TestIsDeleted:
    def test_deleted(self) -> None:
        assert is_deleted("deleted")

    def test_active_is_not_deleted(self) -> None:
        assert not is_deleted("active")

    def test_null_is_not_deleted(self) -> None:
        assert not is_deleted(None)

    def test_is_deleted_is_exact_inverse_of_is_live(self) -> None:
        for status in ("active", "deleted", None):
            assert is_deleted(status) is not is_live(status)


# ---------------------------------------------------------------------------
# No-re-spelling guards — a second copy of the rule is the drift we forbid.
# ---------------------------------------------------------------------------


def test_deadness_compared_only_through_is_live_is_deleted() -> None:
    """No module hand-compares a lifecycle ``status`` to ``deleted``.

    A literal ``.status == "deleted"`` / ``!= "deleted"`` (or the ``EntityStatus``
    enum form) is a re-spelling of liveness that silently survives a third status
    member.  Route deadness through ``is_live`` / ``is_deleted`` instead.  Only
    ``mixins.py`` (which defines them) may name the literal.  The string form is
    anchored to the ``.status`` attribute so it doesn't catch an unrelated
    ``"deleted"`` value on another enum (e.g. ``ClaimDisplayIdentityState``).
    """
    for needle in (
        '.status == "deleted"',
        '.status != "deleted"',
        "== EntityStatus.DELETED",
        "!= EntityStatus.DELETED",
    ):
        found = offenders(needle, allow={"core/models/mixins.py"})
        assert not found, (
            f"Hand-compared status to deleted ({needle!r}) in {found}. "
            "Use is_live() / is_deleted() from apps.core.models instead."
        )


def test_null_status_q_spelled_only_canonically() -> None:
    """No module hand-builds a ``status__isnull`` ``Q``.

    Every liveness ``Q`` must include the null-inclusive clause — forgetting it
    is the classic divergence.  ``active_status_q`` builds that clause once (and
    dynamically, so the literal lives nowhere else); the only other legitimate
    user of a null-status ``Q`` is ``constraints.py``'s domain CHECK.  Anything
    else is a hand-rolled liveness/active filter that must call
    ``active_status_q()`` instead.
    """
    found = offenders("status__isnull", allow={"core/models/constraints.py"})
    assert not found, (
        f"Hand-built a status__isnull Q in {found}. Use active_status_q() "
        "from apps.core.models so the null-inclusive clause can't be dropped."
    )
