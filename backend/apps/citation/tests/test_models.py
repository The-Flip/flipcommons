"""Tests for CitationSource and CitationSourceLink model behavior."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from apps.citation.models import CitationSource, CitationSourceLink


class TestCitationSourceStr:
    def test_name_only(self, db):
        cs = CitationSource.objects.create(name="IPDB", source_type="web")
        assert str(cs) == "IPDB"

    def test_name_and_year(self, db):
        cs = CitationSource.objects.create(
            name="The Encyclopedia of Pinball", source_type="book", year=1996
        )
        assert str(cs) == "The Encyclopedia of Pinball (1996)"

    def test_name_author_year(self, db):
        cs = CitationSource.objects.create(
            name="The Encyclopedia of Pinball",
            source_type="book",
            author="Richard Bueschel",
            year=1996,
        )
        assert str(cs) == "The Encyclopedia of Pinball (Richard Bueschel, 1996)"


class TestCitationSourceTimestamps:
    def test_timestamps_set_on_create(self, citation_source):
        assert citation_source.created_at is not None
        assert citation_source.updated_at is not None

    def test_updated_at_changes_on_save(self, citation_source):
        original = citation_source.updated_at
        citation_source.author = "Updated Author"
        citation_source.save()
        citation_source.refresh_from_db()
        assert citation_source.updated_at > original


class TestCitationSourceRootChild:
    """The named root/child distinction: ``is_root`` + ``roots()``/``children()``."""

    def test_is_root(self, citation_source_with_parent):
        child = citation_source_with_parent
        parent = child.parent
        assert parent.is_root is True
        assert child.is_root is False

    def test_roots_and_children_partition(self, citation_source_with_parent):
        child = citation_source_with_parent
        parent = child.parent
        roots = list(CitationSource.objects.roots())
        children = list(CitationSource.objects.children())
        assert parent in roots
        assert child not in roots
        assert child in children
        assert parent not in children

    def test_methods_chain_on_a_filtered_queryset(self, citation_source_with_parent):
        # ``roots()``/``children()`` are queryset methods, so they compose with
        # ``filter()`` — the form the recognizer and seeding call sites use.
        child = citation_source_with_parent
        parent = child.parent
        assert CitationSource.objects.filter(name=parent.name).roots().get() == parent


class TestWebFlatnessGuard:
    """A web source nests one level — root → child, no grandchildren."""

    def test_rejects_a_web_grandchild(self, db):
        root = CitationSource.objects.create(name="Site", source_type="web")
        child = CitationSource.objects.create(
            name="Page", source_type="web", parent=root
        )
        grandchild = CitationSource(name="Sub-page", source_type="web", parent=child)
        with pytest.raises(ValidationError, match="nests only one level"):
            grandchild.full_clean()

    def test_accepts_a_web_child_under_a_root(self, db):
        root = CitationSource.objects.create(name="Site", source_type="web")
        child = CitationSource(name="Page", source_type="web", parent=root)
        child.full_clean()  # does not raise

    def test_dangling_parent_id_defers_to_the_fk_validator(self, db):
        # The guard must not mask the FK field validator: a non-existent
        # parent_id is a ValidationError (the FK field's job), never a raw
        # DoesNotExist leaking out of clean().
        orphan = CitationSource(name="x", source_type="web", parent_id=999999)
        with pytest.raises(ValidationError):
            orphan.full_clean()

    def test_accepts_book_three_level_nesting(self, db):
        # Book is not a flat-hierarchy type, so deep nesting stays valid.
        root = CitationSource.objects.create(name="Book", source_type="book")
        edition = CitationSource.objects.create(
            name="2nd Edition", source_type="book", parent=root
        )
        page = CitationSource(name="Page 42", source_type="book", parent=edition)
        page.full_clean()  # does not raise


class TestCitationSourceRelationships:
    def test_children_relationship(self, citation_source):
        child = CitationSource.objects.create(
            name="Child", source_type="book", parent=citation_source
        )
        assert child in citation_source.children.all()

    def test_links_relationship(self, citation_source, citation_source_link):
        assert citation_source_link in citation_source.links.all()

    def test_cascade_deletes_links(self, citation_source, citation_source_link):
        link_pk = citation_source_link.pk
        citation_source.delete()
        assert not CitationSourceLink.objects.filter(pk=link_pk).exists()

    def test_protect_prevents_parent_delete(self, citation_source_with_parent):
        parent = citation_source_with_parent.parent
        with pytest.raises(ProtectedError):
            parent.delete()


class TestCitationSourceLinkStr:
    def test_with_label(self, citation_source_link):
        assert str(citation_source_link) == (
            "archive.org scan (https://archive.org/details/encyclopedia-of-pinball)"
        )

    def test_without_label(self, citation_source):
        link = CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://example.com",
        )
        assert str(link) == "https://example.com"
