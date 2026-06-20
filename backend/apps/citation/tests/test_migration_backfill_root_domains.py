"""Tests for the root-domain backfill data migration.

The migration is exercised by calling its ``RunPython`` callables directly
against the live app registry (no ``django_test_migrations`` dependency). Each
test builds its own citation rows, so it does not rely on production data.

Note these run against the live models, not the frozen migration-state models,
so a future required field on ``CitationSourceRootDomain`` could pass here yet
break the real (historical-model) migration.
"""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)

_migration = importlib.import_module(
    "apps.citation.migrations.0005_backfill_citation_root_domains"
)
backfill_root_domains = _migration.backfill_root_domains
remove_root_domains = _migration.remove_root_domains


def _root(name: str, host: str, *, scheme: str = "https") -> CitationSource:
    root = CitationSource.objects.create(name=name, source_type="web")
    CitationSourceLink.objects.create(
        citation_source=root, link_type="homepage", url=f"{scheme}://{host}/"
    )
    return root


@pytest.mark.django_db
class TestBackfill:
    def test_creates_one_row_per_root_homepage_host(self):
        a = _root("American Pinball", "www.american-pinball.com")
        b = _root("Kineticist", "kineticist.com")

        backfill_root_domains(django_apps, None)

        rows = {rd.host: rd.source_id for rd in CitationSourceRootDomain.objects.all()}
        # www. is stripped on the way in.
        assert rows == {"american-pinball.com": a.id, "kineticist.com": b.id}

    @pytest.mark.parametrize("source_type", ["web", "book", "magazine"])
    def test_backfills_any_root_type(self, source_type):
        # The any-root decision: a host on a non-web root is a recognition row
        # too (the query has no source_type filter).
        root = CitationSource.objects.create(name="A Root", source_type=source_type)
        CitationSourceLink.objects.create(
            citation_source=root, link_type="homepage", url="https://example.test/"
        )

        backfill_root_domains(django_apps, None)

        assert CitationSourceRootDomain.objects.filter(
            host="example.test", source_id=root.id
        ).exists()

    def test_skips_child_homepage_links(self):
        root = _root("American Pinball", "american-pinball.com")
        child = CitationSource.objects.create(
            name="A page", source_type="web", parent=root
        )
        # A mistyped homepage link on a child must not become a recognition host.
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="homepage",
            url="https://child.american-pinball.com/",
        )

        backfill_root_domains(django_apps, None)

        assert list(
            CitationSourceRootDomain.objects.values_list("host", flat=True)
        ) == ["american-pinball.com"]

    def test_same_root_declaring_a_host_twice_is_not_a_collision(self):
        root = _root("American Pinball", "american-pinball.com", scheme="https")
        # Same host, second link (http) on the *same* root.
        CitationSourceLink.objects.create(
            citation_source=root,
            link_type="homepage",
            url="http://american-pinball.com/",
        )

        backfill_root_domains(django_apps, None)

        rd = CitationSourceRootDomain.objects.get(host="american-pinball.com")
        assert rd.source_id == root.id

    def test_audit_raises_on_host_owned_by_two_roots(self):
        # The pre-condition the manual TWiP-duplicate delete satisfies: two roots
        # claiming one host fail loud, before any insert.
        _root("Site One", "shared.example")
        _root("Site Two", "shared.example")

        with pytest.raises(RuntimeError, match="more than one root"):
            backfill_root_domains(django_apps, None)

        assert not CitationSourceRootDomain.objects.exists()


@pytest.mark.django_db
class TestReverse:
    def test_empties_the_table(self):
        _root("Kineticist", "kineticist.com")
        backfill_root_domains(django_apps, None)
        assert CitationSourceRootDomain.objects.exists()

        remove_root_domains(django_apps, None)

        assert not CitationSourceRootDomain.objects.exists()

    def test_reverse_then_reapply_rebuilds_rows(self):
        # Reapply-safety: reverse empties the table so a forward re-run can't trip
        # the host unique.
        _root("Kineticist", "kineticist.com")
        backfill_root_domains(django_apps, None)
        remove_root_domains(django_apps, None)

        backfill_root_domains(django_apps, None)

        assert CitationSourceRootDomain.objects.filter(host="kineticist.com").exists()
