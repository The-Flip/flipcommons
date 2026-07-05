"""Guards for the actor-backfill data migrations (accounts/0004, provenance/0012).

The deploy-critical bit those migrations do is the one-time copy from the legacy
columns into Actor: ``priority`` verbatim, and ``Source.is_enabled`` ->
``resolution_status`` (disabled -> suppressed). Runtime mint/sync is covered by
test_actor_minting / test_actor_sync; this pins the *migration* logic.

Unlike the sibling seed backfills (test_seed_ingest_run_backfill etc.), this
can't call the RunPython function against the live schema: ``actor`` ships NOT
NULL in the same PR, so an actor-less row can't exist at runtime. We drive the
real historical state with MigrationExecutor — apply up to the pre-migration
node, create rows there, then migrate forward and assert.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.migration

_BEFORE = [
    ("accounts", "0003_alter_user_username"),
    ("provenance", "0011_backfill_seed_changesets"),
]
_AFTER = [
    ("accounts", "0004_user_actor"),
    ("provenance", "0012_source_actor_and_changeset_claim_actor"),
]


@pytest.mark.django_db(transaction=True)
def test_actor_backfill_copies_legacy_columns():
    executor = MigrationExecutor(connection)
    try:
        # Rewind to the pre-actor state (User/Source have no actor column yet).
        # Reverse sequentially, provenance before accounts: a single combined
        # backwards plan interleaves the two apps' states and feeds 0012's
        # reverse a state that still thinks User.actor exists after 0004 already
        # dropped the column.
        executor.migrate([_BEFORE[1]])  # provenance -> 0011
        executor.loader.build_graph()
        executor.migrate([_BEFORE[0]])  # accounts -> 0003
        executor.loader.build_graph()
        before = executor.loader.project_state(_BEFORE).apps
        User = before.get_model("accounts", "User")
        Source = before.get_model("provenance", "Source")
        User.objects.create(
            username="alice", email="alice@example.com", password="!", priority=7000
        )
        Source.objects.create(
            name="IPDB", slug="ipdb", source_type="database", priority=10
        )
        Source.objects.create(
            name="Retired",
            slug="retired",
            source_type="database",
            priority=3,
            is_enabled=False,
        )

        # Apply the staged add -> backfill -> non-null migrations.
        executor.loader.build_graph()
        executor.migrate(_AFTER)
        after = executor.loader.project_state(_AFTER).apps
        User = after.get_model("accounts", "User")
        Source = after.get_model("provenance", "Source")

        user = User.objects.get(username="alice")
        assert user.actor.backing_model == "user"
        assert user.actor.priority == 7000
        assert user.actor.resolution_status == "active"

        enabled = Source.objects.get(slug="ipdb")
        assert enabled.actor.backing_model == "source"
        assert enabled.actor.priority == 10
        assert enabled.actor.resolution_status == "active"

        disabled = Source.objects.get(slug="retired")
        assert disabled.actor.priority == 3
        assert disabled.actor.resolution_status == "suppressed"  # is_enabled=False

        assert not User.objects.filter(actor__isnull=True).exists()
        assert not Source.objects.filter(actor__isnull=True).exists()
    finally:
        # Restore the DB to the latest schema for subsequent tests.
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
