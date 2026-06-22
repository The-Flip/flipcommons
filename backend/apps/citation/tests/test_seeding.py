"""Tests for the data-patch ``sources:`` get-or-create path (``seeding``).

Focus: recognition-domain minting and host-based dedup layered onto the
additive ``ensure_root_source`` upsert. Field/link upsert behavior is covered
end-to-end by ``apps/catalog/tests/test_patches.py``.
"""

from __future__ import annotations

import pytest

from apps.citation.models import CitationSource, CitationSourceRootDomain
from apps.citation.seed_data.types import SeedLink
from apps.citation.seeding import _declared_homepage_hosts, ensure_root_source

pytestmark = pytest.mark.django_db


def _homepage(url: str) -> SeedLink:
    return {"url": url, "link_type": "homepage"}


def _node(name, source_type="web", links=None):
    node: dict[str, object] = {"name": name, "source_type": source_type}
    if links is not None:
        node["links"] = links
    return node


class TestDeclaredHomepageHosts:
    """Pure host extraction — no DB."""

    def test_only_homepage_links_contribute(self):
        hosts = _declared_homepage_hosts(
            [
                {"url": "https://home.example/", "link_type": "homepage"},
                {"url": "https://cat.example/c", "link_type": "catalog"},
            ]
        )
        assert hosts == ["home.example"]

    def test_dedups_http_and_https_of_same_host(self):
        hosts = _declared_homepage_hosts(
            [
                _homepage("http://www.example.com/"),
                _homepage("https://example.com/other"),
            ]
        )
        assert hosts == ["example.com"]

    def test_skips_link_with_no_hostname(self):
        hosts = _declared_homepage_hosts(
            [{"url": "mailto:hi@example.com", "link_type": "homepage"}]
        )
        assert hosts == []


class TestRootDomainMinting:
    def test_new_root_mints_normalized_domain(self):
        warnings: list[str] = []
        result = ensure_root_source(
            _node(
                "American Pinball",
                links=[_homepage("https://www.American-Pinball.com/")],
            ),
            warnings=warnings,
        )
        assert result.source_created
        root = CitationSource.objects.get(name="American Pinball")
        assert list(root.root_domains.values_list("host", flat=True)) == [
            "american-pinball.com"
        ]

    def test_any_root_type_mints_domain(self):
        """Any-root, not web-only: a book root with a homepage link gets one."""
        ensure_root_source(
            _node(
                "A Pinball Book",
                source_type="book",
                links=[_homepage("https://pinball-book.example/")],
            ),
            warnings=[],
        )
        root = CitationSource.objects.get(name="A Pinball Book")
        assert root.root_domains.filter(host="pinball-book.example").exists()

    def test_non_homepage_link_mints_no_domain(self):
        ensure_root_source(
            _node(
                "Catalog Only",
                links=[{"url": "https://example.com/c", "link_type": "catalog"}],
            ),
            warnings=[],
        )
        root = CitationSource.objects.get(name="Catalog Only")
        assert not root.root_domains.exists()

    def test_new_root_mints_a_domain_per_distinct_host(self):
        """One root owns many domains — a node may declare several at once."""
        ensure_root_source(
            _node(
                "Rebrand",
                links=[
                    _homepage("https://old-name.example/"),
                    _homepage("https://new-name.example/"),
                ],
            ),
            warnings=[],
        )
        root = CitationSource.objects.get(name="Rebrand")
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "old-name.example",
            "new-name.example",
        }


class TestSeedingDedup:
    def test_redeclare_by_name_with_new_host_adds_domain_no_duplicate(self):
        """A same-named root gaining a new homepage host is found, not duplicated."""
        ensure_root_source(
            _node("TWIP", links=[_homepage("https://twip.example/")]), warnings=[]
        )
        warnings: list[str] = []
        result = ensure_root_source(
            _node("TWIP", links=[_homepage("https://blog.twip.example/")]),
            warnings=warnings,
        )
        assert not result.source_created
        assert CitationSource.objects.filter(name="TWIP").count() == 1
        root = CitationSource.objects.get(name="TWIP")
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "twip.example",
            "blog.twip.example",
        }

    def test_dedup_by_host_under_a_new_name(self):
        """Re-seeding the same host under a different name reuses the host owner."""
        ensure_root_source(
            _node("This Week in Pinball", links=[_homepage("https://twip.example/")]),
            warnings=[],
        )
        before = CitationSource.objects.count()
        warnings: list[str] = []
        result = ensure_root_source(
            _node("TWiP (alt name)", links=[_homepage("https://twip.example/")]),
            warnings=warnings,
        )
        assert not result.source_created
        assert CitationSource.objects.count() == before  # no new root
        assert not CitationSource.objects.filter(name="TWiP (alt name)").exists()
        # The warning names the host-match path and the root it resolved to —
        # not a misleading "TWiP (alt name) already exists".
        assert any(
            "recognition host" in w and "This Week in Pinball" in w for w in warnings
        )

    def test_one_host_owned_plus_one_unowned_mints_only_the_new(self):
        """A single owning root + an unowned host → reuse the root, add the host."""
        root = CitationSource.objects.create(name="Owner", source_type="web")
        CitationSourceRootDomain.objects.create(source=root, host="owned.example")
        result = ensure_root_source(
            _node(
                "Owner",
                links=[
                    _homepage("https://owned.example/"),
                    _homepage("https://fresh.example/"),
                ],
            ),
            warnings=[],
        )
        assert not result.source_created
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "owned.example",
            "fresh.example",
        }

    def test_host_owned_by_a_child_warns_and_does_not_wedge(self):
        """A host illegitimately held by a child (a clean() bypass) must not raise.

        The root-scoped resolver can't see the child's row, so the node resolves
        by name and reaches the mint — which must warn-and-skip the taken host,
        never trip the ``host`` unique and abort the patch run.
        """
        parent = CitationSource.objects.create(name="A Root", source_type="web")
        child = CitationSource.objects.create(
            name="A Child", source_type="web", parent=parent
        )
        # Bypass clean() to plant the pathological child-owned row.
        CitationSourceRootDomain.objects.create(source=child, host="squatted.example")

        warnings: list[str] = []
        result = ensure_root_source(  # must not raise
            _node("Fresh Root", links=[_homepage("https://squatted.example/")]),
            warnings=warnings,
        )
        # The source was still created; only the taken host was skipped.
        assert result.source_created
        new_root = CitationSource.objects.get(name="Fresh Root")
        assert not new_root.root_domains.exists()
        assert any("already owned" in w for w in warnings)

    def test_hosts_spanning_two_roots_warns_and_skips_with_no_writes(self):
        a = CitationSource.objects.create(name="Root A", source_type="web")
        CitationSourceRootDomain.objects.create(source=a, host="a.example")
        b = CitationSource.objects.create(name="Root B", source_type="web")
        CitationSourceRootDomain.objects.create(source=b, host="b.example")

        sources_before = CitationSource.objects.count()
        domains_before = CitationSourceRootDomain.objects.count()
        warnings: list[str] = []
        result = ensure_root_source(
            _node(
                "Spans Two",
                links=[
                    _homepage("https://a.example/"),
                    _homepage("https://b.example/"),
                ],
            ),
            warnings=warnings,
        )
        assert result.source_created is False
        assert result.links_created == 0
        assert CitationSource.objects.count() == sources_before  # no node written
        assert CitationSourceRootDomain.objects.count() == domains_before
        assert any("different roots" in w for w in warnings)
