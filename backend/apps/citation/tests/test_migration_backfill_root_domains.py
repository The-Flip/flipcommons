"""Tests for the root-domain backfill data migration.

The 0005 backfill predates editorial attribution, so it is exercised against the
frozen migration-state models at citation 0006 — *before* the ``created_by`` /
``updated_by`` columns were added (0007) and made non-null (0012). Running it
against the live models would fail on the recognition rows the backfill itself
creates, which now require an actor the historical migration never set. Each
test builds its own citation rows at that state, so it relies on no production
data.
"""

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# State just before ``created_by``/``updated_by`` land on the citation models.
_AT = [("citation", "0006_alter_citationsourcerootdomain_host")]

_migration = importlib.import_module(
    "apps.citation.migrations.0005_backfill_citation_root_domains"
)
backfill_root_domains = _migration.backfill_root_domains
remove_root_domains = _migration.remove_root_domains

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.migration]


@pytest.fixture
def state():
    """Historical app registry at citation 0006 (no attribution columns yet).

    Rewinds the citation app to 0006, yields that frozen ``apps`` (the backfill
    reads its models through it), then restores to the latest schema so later
    tests see the real models.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(_AT)
        executor.loader.build_graph()
        yield executor.loader.project_state(_AT).apps
    finally:
        # Drop the rows built at 0006 before restoring to leaf: the leaf includes
        # 0011, whose fail-fast assertion rejects null-attribution rows (these
        # have no actor, and no flipcommons-catalog source exists to claim them).
        # Children first (the parent FK is PROTECT); deleting cascades to links
        # and recognition domains.
        apps = executor.loader.project_state(_AT).apps
        CitationSource = apps.get_model("citation", "CitationSource")
        CitationSource.objects.filter(parent__isnull=False).delete()
        CitationSource.objects.all().delete()
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _root(apps, name: str, host: str, *, scheme: str = "https"):
    CitationSource = apps.get_model("citation", "CitationSource")
    CitationSourceLink = apps.get_model("citation", "CitationSourceLink")
    root = CitationSource.objects.create(name=name, source_type="web")
    CitationSourceLink.objects.create(
        citation_source=root, link_type="homepage", url=f"{scheme}://{host}/"
    )
    return root


class TestBackfill:
    def test_creates_one_row_per_root_homepage_host(self, state):
        a = _root(state, "American Pinball", "www.american-pinball.com")
        b = _root(state, "Kineticist", "kineticist.com")

        backfill_root_domains(state, None)

        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        rows = {rd.host: rd.source_id for rd in CitationSourceRootDomain.objects.all()}
        # www. is stripped on the way in.
        assert rows == {"american-pinball.com": a.id, "kineticist.com": b.id}

    @pytest.mark.parametrize("source_type", ["web", "book", "magazine"])
    def test_backfills_any_root_type(self, state, source_type):
        # The any-root decision: a host on a non-web root is a recognition row
        # too (the query has no source_type filter).
        CitationSource = state.get_model("citation", "CitationSource")
        CitationSourceLink = state.get_model("citation", "CitationSourceLink")
        root = CitationSource.objects.create(name="A Root", source_type=source_type)
        CitationSourceLink.objects.create(
            citation_source=root, link_type="homepage", url="https://example.test/"
        )

        backfill_root_domains(state, None)

        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        assert CitationSourceRootDomain.objects.filter(
            host="example.test", source_id=root.id
        ).exists()

    def test_skips_child_homepage_links(self, state):
        root = _root(state, "American Pinball", "american-pinball.com")
        CitationSource = state.get_model("citation", "CitationSource")
        CitationSourceLink = state.get_model("citation", "CitationSourceLink")
        child = CitationSource.objects.create(
            name="A page", source_type="web", parent=root
        )
        # A mistyped homepage link on a child must not become a recognition host.
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="homepage",
            url="https://child.american-pinball.com/",
        )

        backfill_root_domains(state, None)

        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        assert list(
            CitationSourceRootDomain.objects.values_list("host", flat=True)
        ) == ["american-pinball.com"]

    def test_same_root_declaring_a_host_twice_is_not_a_collision(self, state):
        root = _root(state, "American Pinball", "american-pinball.com", scheme="https")
        CitationSourceLink = state.get_model("citation", "CitationSourceLink")
        # Same host, second link (http) on the *same* root.
        CitationSourceLink.objects.create(
            citation_source=root,
            link_type="homepage",
            url="http://american-pinball.com/",
        )

        backfill_root_domains(state, None)

        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        rd = CitationSourceRootDomain.objects.get(host="american-pinball.com")
        assert rd.source_id == root.id

    def test_audit_raises_on_host_owned_by_two_roots(self, state):
        # The pre-condition the manual TWiP-duplicate delete satisfies: two roots
        # claiming one host fail loud, before any insert.
        _root(state, "Site One", "shared.example")
        _root(state, "Site Two", "shared.example")

        with pytest.raises(RuntimeError, match="more than one root"):
            backfill_root_domains(state, None)

        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        assert not CitationSourceRootDomain.objects.exists()


class TestReverse:
    def test_empties_the_table(self, state):
        _root(state, "Kineticist", "kineticist.com")
        backfill_root_domains(state, None)
        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        assert CitationSourceRootDomain.objects.exists()

        remove_root_domains(state, None)

        assert not CitationSourceRootDomain.objects.exists()

    def test_reverse_then_reapply_rebuilds_rows(self, state):
        # Reapply-safety: reverse empties the table so a forward re-run can't trip
        # the host unique.
        _root(state, "Kineticist", "kineticist.com")
        backfill_root_domains(state, None)
        remove_root_domains(state, None)

        backfill_root_domains(state, None)

        CitationSourceRootDomain = state.get_model(
            "citation", "CitationSourceRootDomain"
        )
        assert CitationSourceRootDomain.objects.filter(host="kineticist.com").exists()
