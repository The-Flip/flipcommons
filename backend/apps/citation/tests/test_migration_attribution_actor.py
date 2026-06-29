"""Round-trip guard for the editorial-attribution User->Actor data migration.

The deploy-critical bit is the data move, both directions: the forward backfill
(citation 0009) projects each legacy ``created_by``/``updated_by`` User FK to that
user's Actor, and its reverse projects back to the User — leaving a source-backed
actor (a patch-created row) null, since the legacy User-FK schema can't represent
non-user attribution. Driven through the real historical schema with
``MigrationExecutor`` (the columns are renamed/dropped across the staged
expand/backfill/contract, so the RunPython can't run against the live schema).
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# Pin accounts/actors at their leaves so ``project_state`` materializes those
# apps too — citation 0007 predates the actors dependency (added in 0008), so a
# citation-only target would leave ``actors``/``accounts`` out of the state.
_DEPS = [
    ("accounts", "0004_user_actor"),
    ("actors", "0002_alter_actor_priority_help_text"),
]
_BEFORE = [("citation", "0007_citationsourcerootdomain_created_by_and_more"), *_DEPS]
_AFTER = [("citation", "0010_contract_attribution_actor_fks"), *_DEPS]


@pytest.mark.django_db(transaction=True)
def test_attribution_actor_backfill_round_trips():
    executor = MigrationExecutor(connection)
    try:
        # Rewind citation to the pre-actor state: created_by/updated_by are still
        # User FKs, no *_actor columns yet.
        executor.migrate(_BEFORE)
        executor.loader.build_graph()
        before = executor.loader.project_state(_BEFORE).apps
        Actor = before.get_model("actors", "Actor")
        User = before.get_model("accounts", "User")
        CitationSource = before.get_model("citation", "CitationSource")

        user_actor = Actor.objects.create(
            backing_model="user", priority=100, resolution_status="active"
        )
        user = User.objects.create(
            username="alice",
            email="alice@example.com",
            password="!",
            priority=100,
            actor=user_actor,
        )
        CitationSource.objects.create(
            name="By user",
            source_type="web",
            created_by_id=user.pk,
            updated_by_id=user.pk,
        )

        # Forward through expand -> backfill -> contract.
        executor.loader.build_graph()
        executor.migrate(_AFTER)
        after = executor.loader.project_state(_AFTER).apps
        Actor = after.get_model("actors", "Actor")
        CitationSource = after.get_model("citation", "CitationSource")

        by_user = CitationSource.objects.get(name="By user")
        assert by_user.created_by_id == user_actor.pk
        assert by_user.updated_by_id == user_actor.pk

        # A row a data patch created post-migration: attributed to a source actor
        # (no backing user) — the reverse must leave it null, not crash.
        source_actor = Actor.objects.create(
            backing_model="source", priority=50, resolution_status="active"
        )
        CitationSource.objects.create(
            name="By patch",
            source_type="web",
            created_by_id=source_actor.pk,
            updated_by_id=source_actor.pk,
        )

        # Reverse all the way back: contract -> backfill -> expand.
        executor.loader.build_graph()
        executor.migrate(_BEFORE)
        back = executor.loader.project_state(_BEFORE).apps
        CitationSource = back.get_model("citation", "CitationSource")

        by_user = CitationSource.objects.get(name="By user")
        assert by_user.created_by_id == user.pk  # projected back to the user
        assert by_user.updated_by_id == user.pk

        by_patch = CitationSource.objects.get(name="By patch")
        assert by_patch.created_by_id is None  # source actor → no user
        assert by_patch.updated_by_id is None

        # Drop the synthetic rows before restoring to leaf: the leaf includes
        # 0011, whose fail-fast assertion rejects a null-attribution row with no
        # flipcommons-catalog source to claim it (this test creates neither a
        # catalog source nor re-attributable rows).
        CitationSource.objects.all().delete()
    finally:
        # Restore the DB to the latest schema for subsequent tests.
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


# 0011 attributes legacy unattributed citation rows to the catalog source, so it
# needs provenance (for Source.actor) pinned in the state too.
_DEPS_0011 = [
    ("accounts", "0004_user_actor"),
    ("actors", "0002_alter_actor_priority_help_text"),
    (
        "provenance",
        "0016_remove_claim_provenance_claim_needs_review_notes_max_length_and_more",
    ),
]
_BEFORE_0011 = [("citation", "0010_contract_attribution_actor_fks"), *_DEPS_0011]
_AFTER_0011 = [("citation", "0011_attribute_seed_citation_sources"), *_DEPS_0011]


@pytest.mark.django_db(transaction=True)
def test_seed_attribution_backfill_attributes_and_reverse_clears():
    """0011 attributes legacy null citation rows to the flipcommons-catalog actor.

    Forward: a seed-ingest row (null attribution) is attributed to the catalog
    Source's actor. Reverse: source-backed attribution is cleared — required so a
    rollback below provenance.0012 (which deletes source actors) isn't blocked by
    the PROTECT ``created_by``/``updated_by`` FKs.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(_BEFORE_0011)
        executor.loader.build_graph()
        before = executor.loader.project_state(_BEFORE_0011).apps
        Actor = before.get_model("actors", "Actor")
        Source = before.get_model("provenance", "Source")
        CitationSource = before.get_model("citation", "CitationSource")

        catalog_actor = Actor.objects.create(
            backing_model="source", priority=10, resolution_status="active"
        )
        Source.objects.create(
            name="Flipcommons Catalog",
            slug="flipcommons-catalog",
            source_type="database",
            priority=10,
            actor=catalog_actor,
        )
        # A legacy seed-ingest row: created by the old path with no attribution.
        CitationSource.objects.create(name="Legacy", source_type="web")

        # Forward: the null row is attributed to the catalog source actor.
        executor.loader.build_graph()
        executor.migrate(_AFTER_0011)
        after = executor.loader.project_state(_AFTER_0011).apps
        CitationSource = after.get_model("citation", "CitationSource")
        cs = CitationSource.objects.get(name="Legacy")
        assert cs.created_by_id == catalog_actor.pk
        assert cs.updated_by_id == catalog_actor.pk

        # Reverse: source-backed attribution is nulled, dropping the PROTECT
        # references that would otherwise block provenance.0012's source-actor
        # delete on a deeper rollback.
        executor.loader.build_graph()
        executor.migrate(_BEFORE_0011)
        back = executor.loader.project_state(_BEFORE_0011).apps
        CitationSource = back.get_model("citation", "CitationSource")
        cs = CitationSource.objects.get(name="Legacy")
        assert cs.created_by_id is None
        assert cs.updated_by_id is None
    finally:
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
