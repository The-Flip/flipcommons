"""Tests for the authored-slug backfill data migration.

The 0023 backfill is exercised against the frozen migration state at 0023 —
after the nullable ``slug`` column lands but *before* 0024 adds the
required-slug constraint, the only state where a slugless magazine row can
exist to backfill. Each test builds its own rows at that state, so it relies
on no production data.
"""

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# The split point: slug column + backfill applied, constraints (0024) not yet.
_AT = [("citation", "0023_citationsource_slug")]

_migration = importlib.import_module(
    "apps.citation.migrations.0023_citationsource_slug"
)
backfill_slugs = _migration.backfill_slugs

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.migration]


@pytest.fixture
def state():
    """Historical app registry at citation 0023 (column present, no constraints).

    Rewinds the citation app to 0023, yields that frozen ``apps``, then drops
    the rows built here and restores to the latest schema — the leaf includes
    0024, whose required-slug constraint the deliberately-slugless test rows
    would violate on later inserts, and 0011's attribution fail-fast rejects
    them outright.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(_AT)
        executor.loader.build_graph()
        yield executor.loader.project_state(_AT).apps
    finally:
        apps = executor.loader.project_state(_AT).apps
        CitationSource = apps.get_model("citation", "CitationSource")
        CitationSource.objects.filter(parent__isnull=False).delete()
        CitationSource.objects.all().delete()
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _actor(apps):
    Actor = apps.get_model("actors", "Actor")
    return Actor.objects.create(backing_model="user", priority=1)


def _source(apps, name, *, source_type="magazine", parent=None, slug=None):
    CitationSource = apps.get_model("citation", "CitationSource")
    actor = _actor(apps)
    return CitationSource.objects.create(
        name=name,
        source_type=source_type,
        parent=parent,
        slug=slug,
        created_by=actor,
        updated_by=actor,
    )


class TestBackfillSlugs:
    def test_slugifies_roots_and_children(self, state):
        root = _source(state, "GameRoom Magazine")
        child = _source(state, "Test Edition", parent=root)

        backfill_slugs(state, None)

        root.refresh_from_db()
        child.refresh_from_db()
        assert root.slug == "gameroom-magazine"
        assert child.slug == "test-edition"

    def test_dedupes_within_a_parent(self, state):
        root = _source(state, "Billboard")
        first = _source(state, "Vol 2", parent=root)
        second = _source(state, "Vol. 2!", parent=root)  # same slugify result

        backfill_slugs(state, None)

        first.refresh_from_db()
        second.refresh_from_db()
        assert {first.slug, second.slug} == {"vol-2", "vol-2-2"}

    def test_same_name_under_different_parents_keeps_one_slug(self, state):
        a = _source(state, "Billboard")
        b = _source(state, "Cash Box")
        under_a = _source(state, "Vol 2", parent=a)
        under_b = _source(state, "Vol 2", parent=b)

        backfill_slugs(state, None)

        under_a.refresh_from_db()
        under_b.refresh_from_db()
        assert under_a.slug == "vol-2"
        assert under_b.slug == "vol-2"

    def test_leaves_other_types_unslugged(self, state):
        book = _source(state, "The Encyclopedia of Pinball", source_type="book")

        backfill_slugs(state, None)

        book.refresh_from_db()
        assert book.slug is None

    def test_leaves_an_existing_slug_alone(self, state):
        root = _source(state, "RePlay", slug="hand-authored")

        backfill_slugs(state, None)

        root.refresh_from_db()
        assert root.slug == "hand-authored"

    def test_raises_on_a_name_that_slugifies_to_nothing(self, state):
        row = _source(state, "!!!")

        with pytest.raises(RuntimeError, match="slugifies to nothing"):
            backfill_slugs(state, None)

        # The failed run must leave the row addressable by a human, not junk.
        row.refresh_from_db()
        assert row.slug is None

    def test_bounds_long_names_to_the_column_limit(self, state):
        # ``name`` is capped at 500 but ``slug`` at 200 — SQLite would store an
        # over-long slug silently while prod Postgres would fail the migration
        # mid-backfill. Two colliding long names also prove the dedup suffix
        # fits inside the bound.
        long_name = "The Extraordinarily Verbose Coin-Operated Amusement " * 6
        first = _source(state, long_name)
        second = _source(state, long_name + "!")  # same slugify result

        backfill_slugs(state, None)

        first.refresh_from_db()
        second.refresh_from_db()
        for row in (first, second):
            assert row.slug is not None
            assert len(row.slug) <= 200
            # The truncation cut must not leave a trailing hyphen — the slug
            # grammar (and the lowercase/not-empty CHECKs in 0024) reject it.
            assert not row.slug.endswith("-")
        assert first.slug != second.slug
