"""Drive data-backfill migration tests against their historical schema state.

The actor backfills (0010 / 0011 / 0013) ran on a schema where ``Claim.changeset``
and the ``actor`` FKs were still nullable. Once 0014 ("Tighten schema") makes them
NOT NULL, the pre-backfill rows those tests need (changeset-less or ``actor=NULL``)
can't be built through the live models at all. So instead of constructing rows on
the current schema and calling ``_forward(django_apps, ...)``, these tests rewind
the DB to the migration's "before" node with ``MigrationExecutor``, build rows
through the frozen historical ``apps`` (where the columns are still nullable), run
``_forward``/``_reverse`` against that same state, then restore the latest schema.

Mirrors the pattern already used by ``apps.actors.tests.test_actor_backfill_migration``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps


@contextmanager
def historical_apps(*before: tuple[str, str]) -> Iterator[StateApps]:
    """Rewind to ``before`` (one or more ``(app_label, migration)`` leaves), yield
    the frozen historical app registry, then migrate back to the latest schema.

    Rows the caller creates are rolled back before the restore so the forward
    data-migrations (0011 / 0013) re-run on empty tables — otherwise leftover
    rows (especially the broken shapes the fail-fast tests build) would re-trip
    those migrations' own guards during the restore. Requires
    ``@pytest.mark.django_db(transaction=True)`` so the rewind/restore migrations
    run outside any test-wrapping transaction (the schema changes must commit).

    Reverse one target at a time: a single combined backwards plan can interleave
    two apps' states and feed a reverse operation a state it doesn't expect (see
    the sibling test in ``apps.actors``).
    """
    executor = MigrationExecutor(connection)
    try:
        for target in before:
            executor.migrate([target])
            executor.loader.build_graph()
        with transaction.atomic():
            try:
                yield executor.loader.project_state(list(before)).apps
            finally:
                transaction.set_rollback(True)
    finally:
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
