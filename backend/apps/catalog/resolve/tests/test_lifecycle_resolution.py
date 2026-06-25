"""Liveness: one definition, correct over the column and over the resolved status.

``is_live`` is the single liveness predicate (pinned in isolation by
``apps/core/tests/test_liveness_canonical``).  Here it is pinned in the two
compositions catalog reads it through:

* over the **materialized column** — ``is_live(row.status)`` and
  ``active_status_q()`` select exactly the rows ``.active()`` returns.
* over the **resolved status** — ``is_live`` over the winning status claim (the
  canonical :func:`ranked_claims` winner-pick) with a materialized-column
  fallback, covering two cases that are easy to get wrong:

  * ``None``-is-live — a legacy row with no status claim must read as live (so it
    still blocks a delete / still cascades), not as "no winning status claim →
    not live".
  * a ``status=deleted`` claim makes the entity not-live *only if it wins
    resolution* — a lower-priority delete must not.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import CatalogModel, MachineModel, Manufacturer, Title
from apps.catalog.tests.conftest import make_machine_model
from apps.core.models import (
    LIFECYCLE_STATUS_FIELD,
    active_status_q,
    is_deleted,
    is_live,
)
from apps.provenance.claim_ranking_in_db import ranked_claims
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim

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
    column (a row with no status claim reads its already-materialized value).

    Uses the canonical claim ranking (:func:`ranked_claims`) — the same
    winner-pick the production resolver applies when it materializes status.
    """
    winner = ranked_claims(
        entity.claims.filter(field_name=LIFECYCLE_STATUS_FIELD), "claim_key"
    ).first()
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
    make_claim(winning, "status", "active", source=sources["low"])
    make_claim(winning, "status", "deleted", source=sources["high"])
    assert _resolved_status(winning) == "deleted"
    assert not is_live(_resolved_status(winning))

    # Delete loses: a lower-priority delete must not unblock — entity stays live.
    losing = Manufacturer.objects.create(name="Del Loses", slug="del-loses")
    make_claim(losing, "status", "active", source=sources["high"])
    make_claim(losing, "status", "deleted", source=sources["low"])
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
