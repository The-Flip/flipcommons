"""Round-trip test for the 0023 magazine → periodical value rename.

Prod carries seeded magazine rows, so the data operation is load-bearing in
both directions: forward, rows must land as ``periodical`` under the renamed
CHECK; unapplied, they must return to ``magazine`` before the old
magazine-only CHECK is restored — a no-op reverse would strand renamed rows
under a constraint that rejects them (and brick a prod rollback the same
way). Other migration tests also rewind below 0023, so reversibility is
exercised by the suite even without this file; this test is the direct
statement of the contract.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

_BEFORE = [("citation", "0022_alter_citationinstance_quote")]
_AFTER = [("citation", "0023_periodical_source_type")]

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.migration]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


def _make_magazine_row(apps):
    Actor = apps.get_model("actors", "Actor")
    actor = Actor.objects.create(backing_model="user", priority=1)
    CitationSource = apps.get_model("citation", "CitationSource")
    return CitationSource.objects.create(
        name="Billboard",
        source_type="magazine",
        created_by=actor,
        updated_by=actor,
    ).pk


@pytest.fixture
def restore_leaf():
    """Return the schema to the leaf, then drop the rows built here.

    Forward through the leaf first: the row must exist while 0024's backfill
    runs (it slugs it) so the 0025 required-slug constraint holds, and the
    leaf-state model can't delete rows before the slug column exists.
    """
    yield
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    leaf = executor.loader.graph.leaf_nodes()
    executor.migrate(leaf)
    executor.loader.build_graph()
    apps = executor.loader.project_state(leaf).apps
    apps.get_model("citation", "CitationSource").objects.all().delete()


def test_round_trip_renames_rows_both_ways(restore_leaf):
    apps = _migrate(_BEFORE)
    pk = _make_magazine_row(apps)

    apps = _migrate(_AFTER)
    row = apps.get_model("citation", "CitationSource").objects.get(pk=pk)
    assert row.source_type == "periodical"

    apps = _migrate(_BEFORE)
    row = apps.get_model("citation", "CitationSource").objects.get(pk=pk)
    assert row.source_type == "magazine"
