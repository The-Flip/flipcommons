"""Liveness resolves the same whether read in SQL or in memory.

The patch front end computes an entity's liveness *in memory* — winner-pick over
the status cell's claims, with a materialized fallback — instead of going through
the SQL ``.active()``.  These tests pin that the in-memory composition
(:func:`apps.core.models.is_live` over the resolved status) agrees with the
production queryset, including two cases that are easy to get wrong:

* ``None``-is-live — a legacy row with no status claim must read as live (so it
  still blocks a delete / still cascades), not as "no winning status claim → not
  live".
* a same-patch delete drops a referrer *only if its* ``status=deleted`` *claim
  actually wins resolution* — a lower-priority delete must not unblock.

``is_live`` is pinned in isolation by ``apps/core/tests/test_liveness_canonical``;
here it is composed with the real claim winner-pick over real rows.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import CatalogModel, MachineModel, Manufacturer, Title
from apps.catalog.resolve.claim_ranking_in_memory import pick_winners
from apps.catalog.tests.conftest import make_machine_model
from apps.core.models import (
    LIFECYCLE_STATUS_FIELD,
    active_status_q,
    is_deleted,
    is_live,
)
from apps.provenance.models import Claim, Source

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# SQL ⇄ predicate equivalence over the materialized column.
# ---------------------------------------------------------------------------


def test_predicate_matches_active_queryset_over_materialized_status() -> None:
    """``is_live(row.status)`` selects exactly the rows ``.active()`` returns."""
    active = Manufacturer.objects.create(name="Live Co", slug="live-co")
    legacy = Manufacturer.objects.create(name="Legacy Co", slug="legacy-co")
    legacy.status = None  # legacy ingest row, no status claim yet
    legacy.save(update_fields=["status"])
    deleted = Manufacturer.objects.create(
        name="Dead Co", slug="dead-co", status="deleted"
    )

    all_rows = [active, legacy, deleted]
    live_via_predicate = {m.pk for m in all_rows if is_live(m.status)}
    live_via_sql = set(Manufacturer.objects.active().values_list("pk", flat=True))
    assert live_via_predicate == live_via_sql == {active.pk, legacy.pk}

    # is_deleted is the exact complement on the same rows.
    dead_via_predicate = {m.pk for m in all_rows if is_deleted(m.status)}
    assert dead_via_predicate == {deleted.pk}


def test_active_status_q_no_arg_matches_active_method() -> None:
    """The bare ``active_status_q()`` filters identically to ``.active()``."""
    Manufacturer.objects.create(name="A", slug="a")
    Manufacturer.objects.create(name="B", slug="b", status="deleted")
    Manufacturer.objects.create(name="C", slug="c")  # then null it
    Manufacturer.objects.filter(slug="c").update(status=None)

    via_q = set(
        Manufacturer.objects.filter(active_status_q()).values_list("pk", flat=True)
    )
    via_method = set(Manufacturer.objects.active().values_list("pk", flat=True))
    assert via_q == via_method


def test_active_status_q_relation_gates_the_related_row() -> None:
    """The relation form gates on the *related* entity's status (null-inclusive)."""
    live_title = Title.objects.create(name="Live Title", slug="live-title")
    dead_title = Title.objects.create(
        name="Dead Title", slug="dead-title", status="deleted"
    )
    mm_live = make_machine_model(name="MM Live", slug="mm-live", title=live_title)
    # A model under a deleted title — must be gated out.
    make_machine_model(name="MM Dead", slug="mm-dead", title=dead_title)

    gated = set(
        MachineModel.objects.filter(active_status_q("title")).values_list(
            "pk", flat=True
        )
    )
    assert gated == {mm_live.pk}


# ---------------------------------------------------------------------------
# Composition — is_live over the *resolved* status (winner-pick + fallback).
# ---------------------------------------------------------------------------


@pytest.fixture
def sources() -> dict[str, Source]:
    return {
        "low": Source.objects.create(name="Low", source_type="database", priority=10),
        "high": Source.objects.create(
            name="High", source_type="editorial", priority=100
        ),
    }


def _resolved_status(entity: CatalogModel) -> str | None:
    """Resolve status: the winning status claim's value, else the materialized
    column (an untouched cell reads its already-materialized value).

    Committed state only — it does not fold in same-patch pending claims.

    TODO: the patch front end will own a shared ``resolve_status`` over
    (committed + pending) claims; switch this test to call it rather than keep a
    second copy of the winner-pick-then-fallback rule.
    """
    claims = list(entity.claims.select_related("source", "user").all())
    winner = pick_winners(claims).get(LIFECYCLE_STATUS_FIELD)
    if winner is None:
        return entity.status
    resolved: str | None = winner.value
    return resolved


def test_delete_drops_referrer_only_when_the_delete_wins(
    sources: dict[str, Source],
) -> None:
    """A ``status=deleted`` claim makes the entity not-live iff it wins the pick."""
    # Delete wins: high-priority source deletes, low-priority keeps it active.
    winning = Manufacturer.objects.create(name="Del Wins", slug="del-wins")
    Claim.objects.assert_claim(winning, "status", "active", source=sources["low"])
    Claim.objects.assert_claim(winning, "status", "deleted", source=sources["high"])
    assert _resolved_status(winning) == "deleted"
    assert not is_live(_resolved_status(winning))

    # Delete loses: a lower-priority delete must not unblock — entity stays live.
    losing = Manufacturer.objects.create(name="Del Loses", slug="del-loses")
    Claim.objects.assert_claim(losing, "status", "active", source=sources["high"])
    Claim.objects.assert_claim(losing, "status", "deleted", source=sources["low"])
    assert _resolved_status(losing) == "active"
    assert is_live(_resolved_status(losing))


def test_null_status_with_no_claim_is_live_via_materialized_fallback() -> None:
    """A legacy referrer (status NULL, no status claim) reads as live.

    Guards against the environment treating "no winning status claim" as
    not-live: the fallback is the materialized column, and ``is_live(None)`` is
    ``True`` — so the referrer still blocks a same-patch delete.
    """
    legacy = Manufacturer.objects.create(name="Legacy", slug="legacy")
    legacy.status = None
    legacy.save(update_fields=["status"])

    assert not legacy.claims.filter(field_name=LIFECYCLE_STATUS_FIELD).exists()
    assert _resolved_status(legacy) is None
    assert is_live(_resolved_status(legacy))
