"""Unit tests for provenance-app target-aware predicates."""

from __future__ import annotations

import pytest

from apps.core.authz.evaluator import check
from apps.core.authz.purity import assert_predicate_is_pure
from apps.core.authz.test_factories import StubPolicyUser
from apps.core.authz.types import Activity, Allow, DenialCode, Deny
from apps.provenance.authz import is_changeset_author


class _FakeCS:
    """ChangeSet stand-in that structurally satisfies ``ChangeSetPolicyView``.

    Constructed in tests instead of building a real ``ChangeSet`` row so
    the predicate-purity assertion runs with zero queries. The
    Protocol's ``@property`` declarations match these plain attributes
    under mypy's structural-Protocol rules — no cast needed.
    """

    def __init__(self, *, id: int, actor_id: int | None) -> None:
        self.id = id
        self.actor_id = actor_id


def test_author_is_allowed():
    user = StubPolicyUser(id=7, actor_id=70)
    cs = _FakeCS(id=1, actor_id=70)
    decision = is_changeset_author(user, cs, None)
    assert isinstance(decision, Allow)


def test_non_author_is_denied_owner_required():
    user = StubPolicyUser(id=7, actor_id=70)
    cs = _FakeCS(id=1, actor_id=80)
    decision = is_changeset_author(user, cs, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.OWNER_REQUIRED


def test_ingest_changeset_actor_denies_any_user():
    """An ingest ChangeSet's actor is a source — no human's actor matches it."""
    user = StubPolicyUser(id=7, actor_id=70)
    cs = _FakeCS(id=1, actor_id=999)  # the source's actor
    decision = is_changeset_author(user, cs, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.OWNER_REQUIRED


def test_anonymous_actor_id_none_denies_without_raising():
    """Anonymous caller has ``actor_id=None`` — predicate denies, never raises."""
    anon = StubPolicyUser(is_authenticated=False, is_active=False, id=0, actor_id=None)
    cs = _FakeCS(id=1, actor_id=70)
    decision = is_changeset_author(anon, cs, None)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.OWNER_REQUIRED


def test_target_none_raises_type_error():
    """Missing ``target`` is a programming error — surface as TypeError, not 403.

    The guard lives in the evaluator so every target-aware rule gets it
    for free; the predicate itself takes a bare (non-Optional) target.
    """
    user = StubPolicyUser(id=7)
    with pytest.raises(TypeError, match="target-aware"):
        check(user, Activity.CHANGESET_UNDO, target=None)


# The `assert_predicate_is_pure` helper wraps the call in
# `CaptureQueriesContext`, which requires the test DB connection to be
# available — even though the predicate itself does not query. Hence
# the `db` fixture below, in contrast to the launch-time tests above
# which run on stubs alone.


@pytest.mark.django_db
def test_predicate_is_pure_for_author():
    user = StubPolicyUser(id=7, actor_id=70)
    cs = _FakeCS(id=1, actor_id=70)
    decision = assert_predicate_is_pure(is_changeset_author, user, target=cs)
    assert isinstance(decision, Allow)


@pytest.mark.django_db
def test_predicate_is_pure_for_non_author():
    user = StubPolicyUser(id=7, actor_id=70)
    cs = _FakeCS(id=1, actor_id=80)
    decision = assert_predicate_is_pure(is_changeset_author, user, target=cs)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.OWNER_REQUIRED


# ── Launch-predicate pins for `changeset.undo` ────────────────────────
#
# The parametrized completeness tests in
# `apps/core/tests/test_authz_registry_complete.py` skip activities
# whose rules declare a `target` Protocol — those predicates raise
# `TypeError` when called with `target=None`. These activity-specific
# pins replace that coverage for `changeset.undo` so a future
# developer who forgets `is_authenticated` or `email_verified` on the
# rule still gets a CI failure.


def test_changeset_undo_denies_anonymous_with_auth_required():
    anon = StubPolicyUser(is_authenticated=False, is_active=False, id=0, actor_id=None)
    cs = _FakeCS(id=1, actor_id=42)
    decision = check(anon, Activity.CHANGESET_UNDO, target=cs)
    assert isinstance(decision, Deny)
    # is_changeset_author also denies (actor_id None != 42), but AUTH_REQUIRED
    # outranks OWNER_REQUIRED in DENIAL_PRIORITY, so that's what surfaces.
    assert decision.code is DenialCode.AUTH_REQUIRED


def test_changeset_undo_requires_email_verified():
    """Unverified author must still hit `VERIFICATION_REQUIRED`, not slip through."""
    user = StubPolicyUser(
        is_authenticated=True,
        is_active=True,
        is_email_verified=False,
        id=7,
        actor_id=70,
    )
    cs = _FakeCS(id=1, actor_id=70)
    decision = check(user, Activity.CHANGESET_UNDO, target=cs)
    assert isinstance(decision, Deny)
    assert decision.code is DenialCode.VERIFICATION_REQUIRED
