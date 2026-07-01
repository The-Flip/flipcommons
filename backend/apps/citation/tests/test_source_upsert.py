"""Tests for the data-patch ``sources:`` get-or-create path (``source_upsert``).

Focus: recognition-domain minting and host-based dedup layered onto the
additive ``ensure_root_source`` upsert. Field/link upsert behavior is covered
end-to-end by ``apps/catalog/tests/test_patches.py``.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.citation.models import CitationSource, CitationSourceRootDomain
from apps.citation.source_node import SourceLinkNode
from apps.citation.source_upsert import (
    _declared_domains_hosts,
    _declared_homepage_hosts,
    _declared_recognition_hosts,
    detect_host_collision,
    ensure_root_source,
    validate_root_source,
)
from apps.citation.test_factories import make_citation_root_domain, make_citation_source
from apps.provenance.test_factories import make_ingest_source

pytestmark = pytest.mark.django_db


def _homepage(url: str) -> SourceLinkNode:
    return {"url": url, "link_type": "homepage"}


def _node(name, source_type="web", links=None, domains=None):
    node: dict[str, object] = {"name": name, "source_type": source_type}
    if links is not None:
        node["links"] = links
    if domains is not None:
        node["domains"] = domains
    return node


@pytest.fixture
def actor(db):
    """A patch ``Source`` actor — the real attributor of `sources:` rows."""

    return make_ingest_source(
        name="Patch Source",
        slug="patch-source",
        source_type="database",
        priority=50,
    ).actor


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
    def test_new_root_mints_normalized_domain(self, actor):
        warnings: list[str] = []
        result = ensure_root_source(
            _node(
                "American Pinball",
                links=[_homepage("https://www.American-Pinball.com/")],
            ),
            actor=actor,
            warnings=warnings,
        )
        assert result.source_created
        root = CitationSource.objects.get(name="American Pinball")
        assert list(root.root_domains.values_list("host", flat=True)) == [
            "american-pinball.com"
        ]

    def test_any_root_type_mints_domain(self, actor):
        """Any-root, not web-only: a book root with a homepage link gets one."""
        ensure_root_source(
            _node(
                "A Pinball Book",
                source_type="book",
                links=[_homepage("https://pinball-book.example/")],
            ),
            actor=actor,
            warnings=[],
        )
        root = CitationSource.objects.get(name="A Pinball Book")
        assert root.root_domains.filter(host="pinball-book.example").exists()

    def test_non_homepage_link_mints_no_domain(self, actor):
        ensure_root_source(
            _node(
                "Catalog Only",
                links=[{"url": "https://example.com/c", "link_type": "catalog"}],
            ),
            actor=actor,
            warnings=[],
        )
        root = CitationSource.objects.get(name="Catalog Only")
        assert not root.root_domains.exists()

    def test_new_root_mints_a_domain_per_distinct_host(self, actor):
        """One root owns many domains — a node may declare several at once."""
        ensure_root_source(
            _node(
                "Rebrand",
                links=[
                    _homepage("https://old-name.example/"),
                    _homepage("https://new-name.example/"),
                ],
            ),
            actor=actor,
            warnings=[],
        )
        root = CitationSource.objects.get(name="Rebrand")
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "old-name.example",
            "new-name.example",
        }


class TestSourceUpsertDedup:
    def test_redeclare_by_name_with_new_host_adds_domain_no_duplicate(self, actor):
        """A same-named root gaining a new homepage host is found, not duplicated."""
        ensure_root_source(
            _node("TWIP", links=[_homepage("https://twip.example/")]),
            actor=actor,
            warnings=[],
        )
        warnings: list[str] = []
        result = ensure_root_source(
            _node("TWIP", links=[_homepage("https://blog.twip.example/")]),
            actor=actor,
            warnings=warnings,
        )
        assert not result.source_created
        assert CitationSource.objects.filter(name="TWIP").count() == 1
        root = CitationSource.objects.get(name="TWIP")
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "twip.example",
            "blog.twip.example",
        }

    def test_dedup_by_host_under_a_new_name(self, actor):
        """Re-declaring the same host under a different name reuses the host owner."""
        ensure_root_source(
            _node("This Week in Pinball", links=[_homepage("https://twip.example/")]),
            actor=actor,
            warnings=[],
        )
        before = CitationSource.objects.count()
        warnings: list[str] = []
        result = ensure_root_source(
            _node("TWiP (alt name)", links=[_homepage("https://twip.example/")]),
            actor=actor,
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

    def test_one_host_owned_plus_one_unowned_mints_only_the_new(self, actor):
        """A single owning root + an unowned host → reuse the root, add the host."""
        root = make_citation_source(name="Owner", source_type="web")
        make_citation_root_domain(source=root, host="owned.example")
        result = ensure_root_source(
            _node(
                "Owner",
                links=[
                    _homepage("https://owned.example/"),
                    _homepage("https://fresh.example/"),
                ],
            ),
            actor=actor,
            warnings=[],
        )
        assert not result.source_created
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "owned.example",
            "fresh.example",
        }

    def test_host_owned_by_a_child_warns_and_does_not_wedge(self, actor):
        """A host illegitimately held by a child (a clean() bypass) must not raise.

        The root-scoped resolver can't see the child's row, so the node resolves
        by name and reaches the mint — which must warn-and-skip the taken host,
        never trip the ``host`` unique and abort the patch run.
        """
        parent = make_citation_source(name="A Root", source_type="web")
        child = make_citation_source(name="A Child", source_type="web", parent=parent)
        # Bypass clean() to plant the pathological child-owned row.
        make_citation_root_domain(source=child, host="squatted.example")

        warnings: list[str] = []
        result = ensure_root_source(  # must not raise
            _node("Fresh Root", links=[_homepage("https://squatted.example/")]),
            actor=actor,
            warnings=warnings,
        )
        # The source was still created; only the taken host was skipped.
        assert result.source_created
        new_root = CitationSource.objects.get(name="Fresh Root")
        assert not new_root.root_domains.exists()
        assert any("already owned" in w for w in warnings)

    def test_hosts_spanning_two_roots_warns_and_skips_with_no_writes(self, actor):
        a = make_citation_source(name="Root A", source_type="web")
        make_citation_root_domain(source=a, host="a.example")
        b = make_citation_source(name="Root B", source_type="web")
        make_citation_root_domain(source=b, host="b.example")

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
            actor=actor,
            warnings=warnings,
        )
        assert result.source_created is False
        assert result.links_created == 0
        assert CitationSource.objects.count() == sources_before  # no node written
        assert CitationSourceRootDomain.objects.count() == domains_before
        # The warning names both owning roots — the merge backlog until gardening.
        assert any(
            "different roots" in w and "Root A" in w and "Root B" in w for w in warnings
        )


class TestDeclaredDomainsHosts:
    """Pure host extraction for the ``domains:`` verb — no DB."""

    def test_bare_host_and_url_normalize_identically(self):
        assert _declared_domains_hosts(_node("x", domains=["oldpin.com"])) == [
            "oldpin.com"
        ]
        assert _declared_domains_hosts(
            _node("x", domains=["https://www.OldPin.com/path"])
        ) == ["oldpin.com"]

    def test_recognition_set_unions_homepage_and_domains_deduped(self):
        node = _node(
            "x",
            links=[_homepage("https://pinballnow.com/")],
            domains=["oldpin.com", "https://pinballnow.com/"],
        )
        # homepage first, then the declared-only host; the dup is dropped.
        assert _declared_recognition_hosts(node) == ["pinballnow.com", "oldpin.com"]


class TestDeclaredDomainsMinting:
    def test_subdomain_is_minted_verbatim_no_rounding(self, actor):
        """A declared subdomain stays its own host — declare does not round."""
        result = ensure_root_source(
            _node("TWIP", domains=["twip.kineticist.com"]), actor=actor, warnings=[]
        )
        assert result.source_created
        root = CitationSource.objects.get(name="TWIP")
        assert list(root.root_domains.values_list("host", flat=True)) == [
            "twip.kineticist.com"
        ]

    def test_homepage_and_domains_union_onto_one_root(self, actor):
        ensure_root_source(
            _node(
                "Pinball Now",
                links=[_homepage("https://pinballnow.com/")],
                domains=["oldpin.com"],
            ),
            actor=actor,
            warnings=[],
        )
        root = CitationSource.objects.get(name="Pinball Now")
        assert set(root.root_domains.values_list("host", flat=True)) == {
            "pinballnow.com",
            "oldpin.com",
        }

    def test_url_form_domain_normalizes_like_bare_form(self, actor):
        ensure_root_source(
            _node("Pinball Now", domains=["https://OldPin.com/"]),
            actor=actor,
            warnings=[],
        )
        root = CitationSource.objects.get(name="Pinball Now")
        assert root.root_domains.filter(host="oldpin.com").exists()


class TestRebrandResolution:
    def test_rebrand_resolves_to_existing_root_via_domains_no_second_root(self, actor):
        """``domains:`` declares the old host; the new homepage adds, not forks.

        The canonical rebrand: an existing root owns ``oldpin.com``; a node with
        ``homepage: pinballnow.com, domains: [oldpin.com]`` must resolve **to that
        root** (because the unified set feeds resolution) and add the new host —
        never mint a second root.
        """
        existing = make_citation_source(name="OldPin", source_type="web")
        make_citation_root_domain(source=existing, host="oldpin.com")
        before = CitationSource.objects.count()

        result = ensure_root_source(
            _node(
                "Pinball Now",
                links=[_homepage("https://pinballnow.com/")],
                domains=["oldpin.com"],
            ),
            actor=actor,
            warnings=[],
        )
        assert not result.source_created
        assert CitationSource.objects.count() == before  # no second root minted
        assert not CitationSource.objects.filter(name="Pinball Now").exists()
        existing.refresh_from_db()
        assert set(existing.root_domains.values_list("host", flat=True)) == {
            "oldpin.com",
            "pinballnow.com",
        }

    def test_domains_host_held_by_a_child_warn_skips_no_integrity_error(self, actor):
        """A declared domain a *child* squats must warn-skip at mint, not raise.

        The root-scoped resolver can't see the child's row, so the node resolves
        by name and reaches the mint; the unified host set flows through the same
        warn-skip the homepage path uses, never tripping the ``host`` unique.
        """
        parent = make_citation_source(name="A Root", source_type="web")
        child = make_citation_source(name="A Child", source_type="web", parent=parent)
        # Bypass clean() to plant the pathological child-owned row.
        make_citation_root_domain(source=child, host="squatted.example")

        warnings: list[str] = []
        result = ensure_root_source(  # must not raise
            _node("Fresh", domains=["squatted.example", "free.example"]),
            actor=actor,
            warnings=warnings,
        )
        assert result.source_created
        root = CitationSource.objects.get(name="Fresh")
        assert list(root.root_domains.values_list("host", flat=True)) == [
            "free.example"
        ]
        assert any("already owned" in w for w in warnings)

    def test_domains_spanning_two_roots_skips_naming_both(self, actor):
        a = make_citation_source(name="Root A", source_type="web")
        make_citation_root_domain(source=a, host="a.example")
        b = make_citation_source(name="Root B", source_type="web")
        make_citation_root_domain(source=b, host="b.example")

        warnings: list[str] = []
        result = ensure_root_source(
            _node("Spans Two", domains=["a.example", "b.example"]),
            actor=actor,
            warnings=warnings,
        )
        assert result.source_created is False
        assert any(
            "different roots" in w and "Root A" in w and "Root B" in w for w in warnings
        )


class TestValidateRootSourceHosts:
    """The read-phase guard validates the unified host set via the model."""

    def test_public_suffix_domain_is_rejected(self):
        with pytest.raises(ValidationError):
            validate_root_source(_node("Bad", domains=["co.uk"]))

    def test_non_dns_domain_is_rejected(self):
        with pytest.raises(ValidationError):
            validate_root_source(_node("Bad", domains=["127.0.0.1"]))

    def test_malformed_ipv6_url_domain_is_rejected_not_raised_raw(self):
        """``urlparse(...).hostname`` raises ValueError on an unbalanced IPv6
        bracket; the extractor must route it to the model guard so it surfaces as
        a ValidationError (→ PatchError), never a raw traceback at read phase."""
        with pytest.raises(ValidationError):
            validate_root_source(_node("Bad", domains=["https://[::1/page"]))

    def test_bad_homepage_host_now_fails_at_validate(self):
        """Flagged behavior change: a public-suffix homepage host fails here too."""
        with pytest.raises(ValidationError):
            validate_root_source(_node("Bad", links=[_homepage("https://co.uk/")]))

    def test_valid_domains_pass(self):
        validate_root_source(
            _node(
                "Good",
                links=[_homepage("https://pinballnow.com/")],
                domains=["oldpin.com", "twip.kineticist.com"],
            )
        )


class TestDetectHostCollision:
    """The committed-state collision preview the dry-run path emits."""

    def test_hosts_spanning_two_roots_returns_warning_naming_both(self):
        a = make_citation_source(name="Root A", source_type="web")
        make_citation_root_domain(source=a, host="a.example")
        b = make_citation_source(name="Root B", source_type="web")
        make_citation_root_domain(source=b, host="b.example")

        warning = detect_host_collision(
            _node("Spans Two", domains=["a.example", "b.example"])
        )
        assert warning is not None
        assert "Root A" in warning
        assert "Root B" in warning

    def test_single_owning_root_is_not_a_collision(self):
        """One owner means the node resolves to it — normal dedup, no warning."""
        owner = make_citation_source(name="Owner", source_type="web")
        make_citation_root_domain(source=owner, host="owned.example")
        assert (
            detect_host_collision(
                _node("X", domains=["owned.example", "fresh.example"])
            )
            is None
        )

    def test_unowned_hosts_are_not_a_collision(self):
        assert detect_host_collision(_node("X", domains=["fresh.example"])) is None


class TestSourceUpsertAttribution:
    """Every row a `sources:` upsert creates is attributed to the patch actor.

    Exercises the three create branches in one pass: ``_create_source`` (the
    root), ``_create_link`` (its homepage link) and ``_ensure_root_domains``
    (its recognition domain).
    """

    def test_created_rows_carry_the_actor(self, actor):
        result = ensure_root_source(
            _node(
                "Attributed Site",
                links=[_homepage("https://attributed.example/")],
            ),
            actor=actor,
            warnings=[],
        )
        assert result.source_created
        root = CitationSource.objects.get(name="Attributed Site")
        assert root.created_by == actor
        assert root.updated_by == actor
        link = root.links.get()
        assert link.created_by == actor
        assert link.updated_by == actor
        domain = root.root_domains.get()
        assert domain.created_by == actor
        assert domain.updated_by == actor
