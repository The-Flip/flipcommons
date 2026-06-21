"""Tests for citation API endpoints."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.citation.extraction import ExtractionDraft, ExtractionResult
from apps.citation.extractors import Recognition
from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)

pytestmark = pytest.mark.django_db


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def _patch(client, path, body):
    return client.patch(path, data=json.dumps(body), content_type="application/json")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearchCitationSources:
    def test_anonymous_gets_401(self, client):
        resp = client.get("/api/citation-sources/search/?q=test")
        assert resp.status_code in (401, 403)

    def test_empty_q_returns_empty_results(self, client, user):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"results": [], "recognition": None}

    def test_whitespace_q_returns_empty_results(self, client, user):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=   ")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"results": [], "recognition": None}

    def test_search_by_name(self, client, user, citation_source):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Encyclopedia")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == citation_source.name

    def test_search_by_author(self, client, user, citation_source_full):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Bueschel")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1

    def test_search_by_publisher(self, client, user, citation_source_full):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Silverball")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1

    def test_search_by_isbn(self, client, user, citation_source_full):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=0964359219")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1

    def test_search_by_linked_url(
        self, client, user, citation_source, citation_source_link
    ):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=archive.org")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == citation_source.pk

    def test_search_case_insensitive(self, client, user, citation_source):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=encyclopedia")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1

    def test_search_max_20_results(self, client, user, db):
        for i in range(25):
            CitationSource.objects.create(name=f"Test Source {i}", source_type="book")
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Test Source")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 20

    def test_search_response_shape(self, client, user, citation_source_full):
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Encyclopedia")
        data = resp.json()
        assert set(data.keys()) == {"results", "recognition"}
        result = data["results"][0]
        assert set(result.keys()) == {
            "id",
            "name",
            "source_type",
            "author",
            "publisher",
            "year",
            "isbn",
            "parent_id",
            "has_children",
            "is_abstract",
            "skip_locator",
            "identifier_key",
        }

    def test_search_returns_identifier_key(self, client, user, db):
        """Search results include identifier_key when set on the source."""
        CitationSource.objects.create(
            name="Internet Pinball Database",
            source_type="web",
            identifier_key="ipdb",
        )
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Internet Pinball")
        assert resp.status_code == 200
        data = resp.json()["results"][0]
        assert data["identifier_key"] == "ipdb"

    def test_search_returns_empty_identifier_key(self, client, user, citation_source):
        """Search results return empty string for sources without identifier_key."""
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Encyclopedia")
        assert resp.status_code == 200
        data = resp.json()["results"][0]
        assert data["identifier_key"] == ""


class TestSearchRecognition:
    """Tests for URL and ISBN recognition in search."""

    def test_ipdb_url_recognized_with_existing_child(self, client, user, db):
        """Pasting an IPDB URL finds the parent and existing child."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        child = CitationSource.objects.create(
            name="IPDB #4443",
            source_type="web",
            parent=parent,
            identifier="4443",
        )
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="homepage",
            url="https://www.ipdb.org/machine.cgi?id=4443",
        )
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/?q=https://www.ipdb.org/machine.cgi?id=4443"
        )
        data = resp.json()
        rec = data["recognition"]
        assert rec is not None
        assert rec["parent"]["id"] == parent.pk
        assert rec["child"]["id"] == child.pk
        assert rec["child"]["skip_locator"] is True
        assert rec["identifier"] == "4443"

    def test_ipdb_url_recognized_no_child(self, client, user, db):
        """Pasting an IPDB URL for a non-existent child returns parent + identifier."""
        CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/?q=https://www.ipdb.org/machine.cgi?id=9999"
        )
        data = resp.json()
        rec = data["recognition"]
        assert rec is not None
        assert rec["parent"]["name"] == "IPDB"
        assert rec["child"] is None
        assert rec["identifier"] == "9999"

    def test_domain_match_jjp_url(self, client, user, db):
        """Pasting a JJP URL domain-matches to the Jersey Jack parent."""
        jjp = CitationSource.objects.create(
            name="Jersey Jack Pinball", source_type="web"
        )
        CitationSourceRootDomain.objects.create(
            source=jjp, host="jerseyjackpinball.com"
        )
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/"
            "?q=https://jerseyjackpinball.com/products/elton-john"
        )
        data = resp.json()
        rec = data["recognition"]
        assert rec is not None
        assert rec["parent"]["id"] == jjp.pk
        assert rec["child"] is None
        assert rec["identifier"] is None

    def test_full_url_matches_existing_child_link(self, client, user, db):
        """Re-pasting a URL that matches an existing child's link returns it."""
        parent = CitationSource.objects.create(
            name="Jersey Jack Pinball", source_type="web"
        )
        CitationSourceLink.objects.create(
            citation_source=parent,
            link_type="homepage",
            url="https://www.jerseyjackpinball.com/",
        )
        child = CitationSource.objects.create(
            name="Elton John Pinball", source_type="web", parent=parent
        )
        url = "https://jerseyjackpinball.com/products/elton-john"
        CitationSourceLink.objects.create(
            citation_source=child, link_type="homepage", url=url
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/search/?q={url}")
        data = resp.json()
        rec = data["recognition"]
        assert rec is not None
        assert rec["child"]["id"] == child.pk

    def test_unknown_url_no_recognition(self, client, user, db):
        """Pasting an unknown URL yields no recognition."""
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/?q=https://unknown-site.com/page"
        )
        data = resp.json()
        assert data["recognition"] is None

    def test_plain_text_no_recognition(self, client, user, citation_source):
        """Plain text searches return no recognition."""
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Encyclopedia")
        data = resp.json()
        assert data["recognition"] is None
        assert len(data["results"]) >= 1

    def test_subdomain_resolves_to_most_specific_root(self, client, user, db):
        """twip.kineticist.com resolves to the TWiP root, not kineticist.com."""
        kineticist = CitationSource.objects.create(name="Kineticist", source_type="web")
        CitationSourceRootDomain.objects.create(
            source=kineticist, host="kineticist.com"
        )
        twip = CitationSource.objects.create(name="TWiP", source_type="web")
        CitationSourceRootDomain.objects.create(source=twip, host="twip.kineticist.com")
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/?q=https://twip.kineticist.com/some-article"
        )
        rec = resp.json()["recognition"]
        assert rec is not None
        assert rec["parent"]["id"] == twip.pk

    def test_source_without_recognition_host_not_matched(self, client, user, db):
        """Recognition keys off CitationSourceRootDomain, not arbitrary links.

        A source with only a reference link (no root-domain row) is not matched.
        """
        source = CitationSource.objects.create(name="Some Source", source_type="web")
        CitationSourceLink.objects.create(
            citation_source=source,
            link_type="reference",
            url="https://en.wikipedia.org/wiki/Pinball",
        )
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/?q=https://en.wikipedia.org/wiki/Something"
        )
        assert resp.json()["recognition"] is None


class TestSearchComputedFields:
    """Tests for is_abstract and skip_locator on search results."""

    def test_root_book_no_children(self, client, user, db):
        """A standalone book: not abstract, needs locator."""
        CitationSource.objects.create(name="Solo Book", source_type="book")
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Solo Book")
        data = resp.json()["results"][0]
        assert data["is_abstract"] is False
        assert data["skip_locator"] is False

    def test_root_book_with_children(self, client, user, db):
        """A book with editions: abstract."""
        parent = CitationSource.objects.create(name="Big Book", source_type="book")
        CitationSource.objects.create(
            name="Big Book Ed. 1", source_type="book", parent=parent
        )
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Big Book")
        results = {r["id"]: r for r in resp.json()["results"]}
        data = results[parent.pk]
        assert data["is_abstract"] is True
        assert data["skip_locator"] is False

    def test_root_web_source(self, client, user, db):
        """A root web source (e.g. IPDB): abstract."""
        CitationSource.objects.create(
            name="Internet Pinball Database",
            source_type="web",
            identifier_key="ipdb",
        )
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Internet Pinball")
        data = resp.json()["results"][0]
        assert data["is_abstract"] is True
        assert data["skip_locator"] is False

    def test_root_web_source_without_identifier_key(self, client, user, db):
        """A root web source without an identifier scheme: abstract."""
        CitationSource.objects.create(name="Jersey Jack Pinball", source_type="web")
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Jersey Jack")
        data = resp.json()["results"][0]
        assert data["is_abstract"] is True
        assert data["skip_locator"] is False

    def test_child_web_source(self, client, user, db):
        """A child web source (e.g. IPDB machine page): skip locator."""
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        child = CitationSource.objects.create(
            name="IPDB Machine 4836", source_type="web", parent=parent
        )
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=IPDB Machine")
        results = {r["id"]: r for r in resp.json()["results"]}
        data = results[child.pk]
        assert data["is_abstract"] is False
        assert data["skip_locator"] is True

    def test_root_magazine(self, client, user, db):
        """A root magazine: abstract."""
        CitationSource.objects.create(name="Pinball Magazine", source_type="magazine")
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Pinball Magazine")
        data = resp.json()["results"][0]
        assert data["is_abstract"] is True
        assert data["skip_locator"] is False


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreateCitationSource:
    def test_anonymous_gets_401(self, client):
        resp = _post(
            client, "/api/citation-sources/", {"name": "X", "source_type": "book"}
        )
        assert resp.status_code in (401, 403)

    def test_minimal_create(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test Book",
                "source_type": "book",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Book"
        assert data["source_type"] == "book"
        assert data["author"] == ""
        assert data["links"] == []
        assert data["children"] == []

    def test_full_create(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "The Encyclopedia of Pinball Vol 1",
                "source_type": "book",
                "author": "Richard Bueschel",
                "publisher": "Silverball Amusements",
                "year": 1996,
                "month": 6,
                "day": 15,
                "date_note": "",
                "isbn": "1234567890",
                "description": "A great book.",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["year"] == 1996
        assert data["month"] == 6
        assert data["isbn"] == "1234567890"

    def test_create_with_parent(self, client, user, citation_source):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Edition 2",
                "source_type": "book",
                "parent_id": citation_source.pk,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["parent"]["id"] == citation_source.pk
        assert data["parent"]["name"] == citation_source.name

    def test_create_sets_created_by_and_updated_by(self, client, user):
        client.force_login(user)
        _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test",
                "source_type": "book",
            },
        )
        source = CitationSource.objects.get(name="Test")
        assert source.created_by == user
        assert source.updated_by == user

    def test_invalid_source_type_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test",
                "source_type": "podcast",
            },
        )
        assert resp.status_code == 422

    def test_empty_name_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "",
                "source_type": "book",
            },
        )
        assert resp.status_code == 422

    def test_duplicate_isbn_returns_422(self, client, user, citation_source_full):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Another Book",
                "source_type": "book",
                "isbn": citation_source_full.isbn,
            },
        )
        assert resp.status_code == 422

    def test_month_without_year_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test",
                "source_type": "book",
                "month": 6,
            },
        )
        assert resp.status_code == 422

    def test_day_without_month_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test",
                "source_type": "book",
                "year": 1996,
                "day": 15,
            },
        )
        assert resp.status_code == 422

    def test_nonexistent_parent_returns_404(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test",
                "source_type": "book",
                "parent_id": 99999,
            },
        )
        assert resp.status_code == 404

    def test_mojibake_name_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Ã©ncyclopedia",
                "source_type": "book",
            },
        )
        assert resp.status_code == 422


class TestCreateCitationSourceWithLink:
    """Atomic source + link creation via the optional url field."""

    def test_create_with_url_creates_source_and_link(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Pinball Wiki Page",
                "source_type": "web",
                "url": "https://example.com/pinball",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Pinball Wiki Page"
        assert len(data["links"]) == 1
        assert data["links"][0]["url"] == "https://example.com/pinball"

    def test_create_with_url_and_link_label(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Archive Page",
                "source_type": "web",
                "url": "https://archive.org/details/pinball",
                "link_label": "archive.org",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["links"][0]["label"] == "archive.org"

    def test_create_without_url_creates_no_link(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "A Book",
                "source_type": "book",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["links"] == []

    def test_invalid_url_returns_422_and_creates_no_source(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Bad Link Source",
                "source_type": "web",
                "url": "not-a-url",
            },
        )
        assert resp.status_code == 422
        assert not CitationSource.objects.filter(name="Bad Link Source").exists()

    def test_link_sets_created_by(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Test Web",
                "source_type": "web",
                "url": "https://example.com",
            },
        )
        assert resp.status_code == 201
        link = CitationSourceLink.objects.get(citation_source_id=resp.json()["id"])
        assert link.created_by == user


class TestCreateCitationSourceRootDomain:
    """A parentless source with a homepage link owns a recognition domain."""

    def test_root_with_homepage_mints_normalized_domain(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "American Pinball",
                "source_type": "web",
                "url": "https://www.American-Pinball.com/",
            },
        )
        assert resp.status_code == 201
        domain = CitationSourceRootDomain.objects.get(source_id=resp.json()["id"])
        assert domain.host == "american-pinball.com"

    def test_any_root_type_mints_domain(self, client, user):
        """Any-root, not web-only: a book root with a homepage link gets one."""
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "A Pinball Book",
                "source_type": "book",
                "url": "https://pinball-book.example/",
            },
        )
        assert resp.status_code == 201
        assert CitationSourceRootDomain.objects.filter(
            source_id=resp.json()["id"], host="pinball-book.example"
        ).exists()

    def test_child_mints_no_domain(self, client, user, citation_source):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "A Page",
                "source_type": "web",
                "url": "https://example.com/page",
                "parent_id": citation_source.pk,
            },
        )
        assert resp.status_code == 201
        assert not CitationSourceRootDomain.objects.filter(
            source_id=resp.json()["id"]
        ).exists()

    def test_non_homepage_link_mints_no_domain(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Catalog Root",
                "source_type": "web",
                "url": "https://example.com/catalog",
                "link_type": "catalog",
            },
        )
        assert resp.status_code == 201
        assert not CitationSourceRootDomain.objects.filter(
            source_id=resp.json()["id"]
        ).exists()

    def test_second_root_claiming_same_host_returns_422(self, client, user):
        client.force_login(user)
        first = _post(
            client,
            "/api/citation-sources/",
            {"name": "First", "source_type": "web", "url": "https://example.com/"},
        )
        assert first.status_code == 201
        second = _post(
            client,
            "/api/citation-sources/",
            {"name": "Second", "source_type": "web", "url": "https://example.com/x"},
        )
        assert second.status_code == 422
        assert "already recognized" in second.json()["detail"]
        # The whole create rolled back — no orphaned second source.
        assert not CitationSource.objects.filter(name="Second").exists()


class TestCiteUrl:
    """The interactive web-create finalize endpoint, ``POST /cite-url/``."""

    URL = "/api/citation-sources/cite-url/"

    def test_anonymous_gets_401(self, client):
        resp = _post(client, self.URL, {"url": "https://example.com/page"})
        assert resp.status_code in (401, 403)

    def test_no_match_creates_root_and_child_at_raw_host(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            self.URL,
            {
                "url": "https://blog.newsite.example/post",
                "site_name": "New Site",
                "site_description": "A site.",
                "page_name": "A Post",
            },
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.name == "A Post"
        assert child.parent is not None
        # Roots at the RAW pasted host (PR 2 rounds to the registrable domain).
        root = child.parent
        assert root.name == "New Site"
        assert root.description == "A site."
        assert root.parent_id is None
        domain = CitationSourceRootDomain.objects.get(source=root)
        assert domain.host == "blog.newsite.example"
        assert (
            root.links.get(link_type="homepage").url == "https://blog.newsite.example/"
        )
        assert child.links.get(link_type="reference").url == (
            "https://blog.newsite.example/post"
        )

    def test_no_match_attributes_every_row_to_caller(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            self.URL,
            {"url": "https://newsite.example/x", "page_name": "X"},
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        root = child.parent
        assert root is not None
        assert child.created_by == user
        assert child.updated_by == user
        assert root.created_by == user
        assert root.updated_by == user
        for link in CitationSourceLink.objects.filter(
            citation_source__in=[root, child]
        ):
            assert link.created_by == user
            assert link.updated_by == user

    def test_blank_site_name_falls_back_to_host(self, client, user):
        client.force_login(user)
        resp = _post(client, self.URL, {"url": "https://newsite.example/p"})
        assert resp.status_code == 201
        root = CitationSource.objects.get(pk=resp.json()["id"]).parent
        assert root is not None
        assert root.name == "newsite.example"

    def test_response_is_the_web_child(self, client, user):
        client.force_login(user)
        resp = _post(
            client, self.URL, {"url": "https://newsite.example/p", "page_name": "P"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "P"
        # A web child skips the locator stage — its URL is the locator.
        assert data["skip_locator"] is True

    def test_domain_match_nests_child_and_ignores_site_fields(self, client, user):
        client.force_login(user)
        root = CitationSource.objects.create(name="Existing", source_type="web")
        CitationSourceRootDomain.objects.create(source=root, host="existing.example")
        resp = _post(
            client,
            self.URL,
            {
                "url": "https://existing.example/article",
                "site_name": "IGNORED",
                "site_description": "IGNORED",
                "page_name": "Article",
            },
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.parent_id == root.pk
        # The child and its link are attributed to the caller (this path mints
        # via the same _create_web_child helper but isn't covered by the
        # no-match attribution test).
        assert child.created_by == user
        assert child.updated_by == user
        ref = child.links.get(link_type="reference")
        assert ref.created_by == user
        assert ref.updated_by == user
        # The root is never renamed/redescribed from here.
        root.refresh_from_db()
        assert root.name == "Existing"
        assert root.description == ""
        # No second root was created.
        assert CitationSource.objects.filter(parent__isnull=True).count() == 1

    def test_subdomain_of_seeded_root_nests_under_it(self, client, user):
        client.force_login(user)
        root = CitationSource.objects.create(name="American Pinball", source_type="web")
        CitationSourceRootDomain.objects.create(
            source=root, host="american-pinball.com"
        )
        resp = _post(
            client,
            self.URL,
            {"url": "https://s4.american-pinball.com/manual.pdf"},
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.parent_id == root.pk
        # No page_name sent → the child name falls back to the URL.
        assert child.name == "https://s4.american-pinball.com/manual.pdf"
        assert not CitationSourceRootDomain.objects.filter(
            host="s4.american-pinball.com"
        ).exists()

    def test_exact_child_is_reused(self, client, user):
        client.force_login(user)
        root = CitationSource.objects.create(name="Existing", source_type="web")
        CitationSourceRootDomain.objects.create(source=root, host="existing.example")
        child = CitationSource.objects.create(
            name="Page", source_type="web", parent=root
        )
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="reference",
            url="https://existing.example/page",
        )
        before = CitationSource.objects.count()
        resp = _post(client, self.URL, {"url": "https://existing.example/page"})
        assert resp.status_code == 201
        assert resp.json()["id"] == child.pk
        assert CitationSource.objects.count() == before

    def test_scheme_url_returns_422(self, client, user):
        client.force_login(user)
        CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(
            client,
            self.URL,
            {"url": "https://www.ipdb.org/machine.cgi?id=4443"},
        )
        assert resp.status_code == 422
        assert "scheme" in resp.json()["detail"].lower()
        assert not CitationSource.objects.filter(parent__isnull=False).exists()

    def test_scheme_url_with_existing_child_still_422(self, client, user):
        """identifier is checked before child, so a scheme URL never reuses here.

        Even when the scheme child already exists (recognize_url sets both
        identifier and child), cite-url must 422 — the caller has to use
        ``scheme:identifier`` — not silently reuse the child.
        """
        client.force_login(user)
        root = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        child = CitationSource.objects.create(
            name="IPDB #4443", source_type="web", parent=root, identifier="4443"
        )
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="reference",
            url="https://www.ipdb.org/machine.cgi?id=4443",
        )
        resp = _post(
            client, self.URL, {"url": "https://www.ipdb.org/machine.cgi?id=4443"}
        )
        assert resp.status_code == 422
        assert "scheme" in resp.json()["detail"].lower()

    def test_hostless_url_returns_422_no_500(self, client, user):
        client.force_login(user)
        resp = _post(client, self.URL, {"url": "mailto:someone@example.com"})
        assert resp.status_code == 422
        assert CitationSource.objects.count() == 0

    def test_root_domain_guard_failure_returns_422_not_500(self, client, user):
        """A domain-model guard surfaces as the declared 422 and rolls back.

        No ``clean()`` rule rejects a normalized parentless host in this PR, so
        we stand in for the forthcoming PR-2 public-suffix guard by making the
        domain's ``full_clean`` raise: the point is that a ``ValidationError``
        on the root-domain row becomes a 422 (Django ValidationError has no API
        exception handler, so an uncaught one would 500) and the whole create
        rolls back.
        """
        client.force_login(user)

        def reject(self, *args, **kwargs):
            raise ValidationError({"host": "Not an allowed recognition host."})

        with patch.object(CitationSourceRootDomain, "full_clean", reject):
            resp = _post(client, self.URL, {"url": "https://blocked.example/p"})
        assert resp.status_code == 422
        assert CitationSource.objects.count() == 0

    def test_root_create_race_re_recognizes_and_nests(self, client, user):
        """A concurrent host-unique violation rolls back and nests the child.

        A true concurrent commit can't be staged inside the test's own
        transaction (it'd roll back with our savepoint), so we drive the
        except-branch directly: the domain insert raises ``IntegrityError`` as
        it would on a lost race, and the re-recognition then matches the root
        the racer committed.
        """
        client.force_login(user)
        racer = CitationSource.objects.create(name="Racer", source_type="web")

        def raise_integrity(self, *args, **kwargs):
            raise IntegrityError("duplicate key value violates unique constraint")

        rematch = Recognition(parent_id=racer.pk, parent_name="Racer")
        with (
            patch.object(CitationSourceRootDomain, "save", raise_integrity),
            patch("apps.citation.api.recognize_url", side_effect=[None, rematch]),
        ):
            resp = _post(
                client, self.URL, {"url": "https://raced.example/p", "page_name": "P"}
            )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        # Nested under the racer's root, not a duplicate, no 500.
        assert child.parent_id == racer.pk
        assert CitationSource.objects.filter(name="P").count() == 1
        # The savepoint rolled back the attempted root + its homepage link (blank
        # site_name → it was named after the host), leaving only the racer root.
        assert not CitationSource.objects.filter(name="raced.example").exists()
        assert CitationSource.objects.filter(parent__isnull=True).count() == 1


class TestCreateCitationSourceWithIdentifier:
    """Creating children with identifier: validation, normalization, auto-naming."""

    def test_bare_id_creates_child_with_canonical_url(self, client, user, db):
        """A valid bare identifier auto-builds name and canonical URL."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "4443",
                "source_type": "web",
                "parent_id": parent.pk,
                "identifier": "4443",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "IPDB #4443"
        assert len(data["links"]) == 1
        assert data["links"][0]["url"] == "https://www.ipdb.org/machine.cgi?id=4443"

    def test_pasted_url_normalized_to_bare_id(self, client, user, db):
        """A full IPDB URL as identifier is normalized to the bare ID."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "",
                "source_type": "web",
                "parent_id": parent.pk,
                "identifier": "https://www.ipdb.org/machine.cgi?id=4443",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "IPDB #4443"
        child = CitationSource.objects.get(pk=data["id"])
        assert child.identifier == "4443"

    def test_invalid_identifier_returns_422(self, client, user, db):
        """An identifier that doesn't match the extractor's format is rejected."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Bad",
                "source_type": "web",
                "parent_id": parent.pk,
                "identifier": "abc",
            },
        )
        assert resp.status_code == 422

    def test_random_url_as_identifier_returns_422(self, client, user, db):
        """A non-IPDB URL passed as identifier is rejected."""
        parent = CitationSource.objects.create(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {
                "name": "Bad",
                "source_type": "web",
                "parent_id": parent.pk,
                "identifier": "https://example.com/page",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


class TestGetCitationSourceDetail:
    def test_anonymous_gets_401(self, client, citation_source):
        resp = client.get(f"/api/citation-sources/{citation_source.pk}/")
        assert resp.status_code in (401, 403)

    def test_get_existing_source(self, client, user, citation_source):
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{citation_source.pk}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == citation_source.name
        assert data["id"] == citation_source.pk

    def test_get_source_with_links_and_children(
        self,
        client,
        user,
        citation_source,
        citation_source_link,
        citation_source_with_parent,
    ):
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{citation_source.pk}/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["links"]) == 1
        assert data["links"][0]["url"] == citation_source_link.url
        assert len(data["children"]) == 1
        assert data["children"][0]["id"] == citation_source_with_parent.pk

    def test_nonexistent_returns_404(self, client, user):
        client.force_login(user)
        resp = client.get("/api/citation-sources/99999/")
        assert resp.status_code == 404

    def test_detail_includes_skip_locator(self, client, user, db):
        """Detail response includes skip_locator field."""
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        child = CitationSource.objects.create(
            name="IPDB Machine 1000", source_type="web", parent=parent
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{child.pk}/")
        assert resp.status_code == 200
        assert resp.json()["skip_locator"] is True

    def test_detail_skip_locator_false_for_book(self, client, user, citation_source):
        """Detail response: skip_locator is false for non-web sources."""
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{citation_source.pk}/")
        assert resp.status_code == 200
        assert resp.json()["skip_locator"] is False

    def test_detail_children_include_skip_locator(self, client, user, db):
        """Children in detail response include skip_locator."""
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        CitationSource.objects.create(
            name="IPDB Machine 2000", source_type="web", parent=parent
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/")
        data = resp.json()
        assert len(data["children"]) == 1
        assert data["children"][0]["skip_locator"] is True

    def test_detail_children_include_urls(self, client, user, db):
        """Children in detail response include their link URLs."""
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        child = CitationSource.objects.create(
            name="IPDB Machine 3000", source_type="web", parent=parent
        )
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="homepage",
            url="https://www.ipdb.org/machine.cgi?id=3000",
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/")
        data = resp.json()
        assert len(data["children"]) == 1
        assert data["children"][0]["urls"] == [
            "https://www.ipdb.org/machine.cgi?id=3000"
        ]

    def test_detail_children_urls_empty_when_no_links(self, client, user, db):
        """Children with no links have an empty urls list."""
        parent = CitationSource.objects.create(name="Big Book", source_type="book")
        CitationSource.objects.create(
            name="Edition 1", source_type="book", parent=parent
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/")
        data = resp.json()
        assert len(data["children"]) == 1
        assert data["children"][0]["urls"] == []


# ---------------------------------------------------------------------------
# Children (filtered)
# ---------------------------------------------------------------------------


class TestListChildren:
    """Tests for GET /api/citation-sources/{id}/children/?q=..."""

    def test_anonymous_gets_401(self, client, citation_source):
        resp = client.get(f"/api/citation-sources/{citation_source.pk}/children/")
        assert resp.status_code in (401, 403)

    def test_empty_q_returns_empty_list(self, client, user, db):
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        CitationSource.objects.create(
            name="IPDB Machine 1000", source_type="web", parent=parent
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/children/?q=")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_filter_by_child_name(self, client, user, db):
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        match = CitationSource.objects.create(
            name="IPDB Machine 4836", source_type="web", parent=parent
        )
        CitationSource.objects.create(
            name="IPDB Machine 9999", source_type="web", parent=parent
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/children/?q=4836")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == match.pk

    def test_filter_by_child_url(self, client, user, db):
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        child = CitationSource.objects.create(
            name="IPDB Machine 4836", source_type="web", parent=parent
        )
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="homepage",
            url="https://www.ipdb.org/machine.cgi?id=4836",
        )
        CitationSource.objects.create(
            name="IPDB Machine 9999", source_type="web", parent=parent
        )
        client.force_login(user)
        resp = client.get(
            f"/api/citation-sources/{parent.pk}/children/?q=ipdb.org/machine.cgi?id=4836"
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == child.pk
        assert results[0]["urls"] == ["https://www.ipdb.org/machine.cgi?id=4836"]

    def test_response_shape_matches_child_schema(self, client, user, db):
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        child = CitationSource.objects.create(
            name="IPDB Machine 5000", source_type="web", parent=parent, year=2020
        )
        CitationSourceLink.objects.create(
            citation_source=child,
            link_type="homepage",
            url="https://www.ipdb.org/machine.cgi?id=5000",
        )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/children/?q=5000")
        data = resp.json()[0]
        assert set(data.keys()) == {
            "id",
            "name",
            "source_type",
            "year",
            "isbn",
            "skip_locator",
            "urls",
        }

    def test_max_20_results(self, client, user, db):
        parent = CitationSource.objects.create(
            name="Internet Pinball Database", source_type="web"
        )
        for i in range(25):
            CitationSource.objects.create(
                name=f"IPDB Machine {i}", source_type="web", parent=parent
            )
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/children/?q=IPDB")
        assert resp.status_code == 200
        assert len(resp.json()) <= 20

    def test_nonexistent_parent_returns_404(self, client, user):
        client.force_login(user)
        resp = client.get("/api/citation-sources/99999/children/?q=test")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdateCitationSource:
    def test_anonymous_gets_401(self, client, citation_source):
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/",
            {
                "name": "New Name",
            },
        )
        assert resp.status_code in (401, 403)

    def test_partial_update_name_only(self, client, user, citation_source):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/",
            {
                "name": "Updated Name",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_partial_update_preserves_unchanged_fields(
        self, client, user, citation_source_full
    ):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source_full.pk}/",
            {
                "name": "Updated",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated"
        assert data["author"] == citation_source_full.author
        assert data["year"] == citation_source_full.year

    def test_update_sets_updated_by(self, client, user, citation_source):
        client.force_login(user)
        _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/",
            {
                "name": "Updated",
            },
        )
        citation_source.refresh_from_db()
        assert citation_source.updated_by == user

    def test_clear_nullable_field(self, client, user, citation_source_full):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source_full.pk}/",
            {
                "year": None,
                "month": None,
                "day": None,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] is None
        assert data["month"] is None

    def test_clear_isbn_via_empty_string(self, client, user, citation_source_full):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source_full.pk}/",
            {
                "isbn": "",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["isbn"] is None

    def test_null_coercion_for_string_field(self, client, user, citation_source_full):
        """Sending null for a non-nullable string field coerces to empty string."""
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source_full.pk}/",
            {
                "author": None,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["author"] == ""

    def test_duplicate_isbn_returns_422(self, client, user, citation_source_full):
        other = CitationSource.objects.create(
            name="Other", source_type="book", isbn="9999999999"
        )
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source_full.pk}/",
            {
                "isbn": other.isbn,
            },
        )
        assert resp.status_code == 422

    def test_no_changes_returns_422(self, client, user, citation_source):
        client.force_login(user)
        resp = _patch(client, f"/api/citation-sources/{citation_source.pk}/", {})
        assert resp.status_code == 422

    def test_nonexistent_returns_404(self, client, user):
        client.force_login(user)
        resp = _patch(client, "/api/citation-sources/99999/", {"name": "X"})
        assert resp.status_code == 404

    def test_day_without_month_after_merge_returns_422(self, client, user):
        """PATCH day on a source with year but no month should fail."""
        source = CitationSource.objects.create(
            name="Test", source_type="book", year=1996
        )
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{source.pk}/",
            {
                "day": 15,
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Create Link
# ---------------------------------------------------------------------------


class TestCreateCitationSourceLink:
    def test_anonymous_gets_401(self, client, citation_source):
        resp = _post(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/",
            {"link_type": "homepage", "url": "https://example.com"},
        )
        assert resp.status_code in (401, 403)

    def test_create_link(self, client, user, citation_source):
        client.force_login(user)
        resp = _post(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/",
            {"link_type": "catalog", "url": "https://example.com", "label": "Example"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["link_type"] == "catalog"
        assert data["url"] == "https://example.com"
        assert data["label"] == "Example"

    def test_create_link_sets_created_by(self, client, user, citation_source):
        client.force_login(user)
        _post(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/",
            {"link_type": "homepage", "url": "https://example.com"},
        )
        link = CitationSourceLink.objects.get(citation_source=citation_source)
        assert link.created_by == user
        assert link.updated_by == user

    def test_duplicate_url_returns_422(
        self, client, user, citation_source, citation_source_link
    ):
        client.force_login(user)
        resp = _post(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/",
            {"link_type": "homepage", "url": citation_source_link.url},
        )
        assert resp.status_code == 422

    def test_nonexistent_source_returns_404(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/99999/links/",
            {"link_type": "homepage", "url": "https://example.com"},
        )
        assert resp.status_code == 404

    def test_invalid_url_returns_422(self, client, user, citation_source):
        client.force_login(user)
        resp = _post(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/",
            {"link_type": "homepage", "url": "not-a-url"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Update Link
# ---------------------------------------------------------------------------


class TestUpdateCitationSourceLink:
    def test_anonymous_gets_401(self, client, citation_source, citation_source_link):
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/{citation_source_link.pk}/",
            {"label": "new"},
        )
        assert resp.status_code in (401, 403)

    def test_update_url(self, client, user, citation_source, citation_source_link):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/{citation_source_link.pk}/",
            {"url": "https://new-url.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://new-url.com"

    def test_update_label(self, client, user, citation_source, citation_source_link):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/{citation_source_link.pk}/",
            {"label": "updated label"},
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "updated label"

    def test_update_sets_updated_by(
        self, client, user, citation_source, citation_source_link
    ):
        client.force_login(user)
        _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/{citation_source_link.pk}/",
            {"label": "updated"},
        )
        citation_source_link.refresh_from_db()
        assert citation_source_link.updated_by == user

    def test_link_on_wrong_source_returns_404(self, client, user, citation_source_link):
        other_source = CitationSource.objects.create(name="Other", source_type="web")
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{other_source.pk}/links/{citation_source_link.pk}/",
            {"label": "hack"},
        )
        assert resp.status_code == 404

    def test_no_changes_returns_422(
        self, client, user, citation_source, citation_source_link
    ):
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/{citation_source_link.pk}/",
            {},
        )
        assert resp.status_code == 422

    def test_duplicate_url_returns_422(
        self, client, user, citation_source, citation_source_link
    ):
        CitationSourceLink.objects.create(
            citation_source=citation_source,
            link_type="homepage",
            url="https://other.com",
            label="other",
        )
        client.force_login(user)
        resp = _patch(
            client,
            f"/api/citation-sources/{citation_source.pk}/links/{citation_source_link.pk}/",
            {"url": "https://other.com"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

EXTRACT_URL = "/api/citation-sources/extract/"


class TestExtractEndpoint:
    @patch("apps.citation.api.extract_isbn")
    def test_extract_isbn_returns_draft(self, mock_extract, client, user):
        client.force_login(user)
        mock_extract.return_value = ExtractionResult(
            draft=ExtractionDraft(
                name="Learning Python",
                source_type="book",
                author="Mark Lutz",
                publisher="O'Reilly Media",
                year=2009,
                isbn="9780596517748",
            ),
            confidence="high",
            source_api="openlibrary",
        )
        resp = _post(client, EXTRACT_URL, {"input": "978-0-596-51774-8"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft"]["name"] == "Learning Python"
        assert data["draft"]["source_type"] == "book"
        assert data["draft"]["author"] == "Mark Lutz"
        assert data["draft"]["publisher"] == "O'Reilly Media"
        assert data["draft"]["year"] == 2009
        assert data["draft"]["isbn"] == "9780596517748"
        assert data["draft"]["url"] is None
        assert data["confidence"] == "high"
        assert data["source_api"] == "openlibrary"
        assert data["match"] is None
        assert data["error"] is None

    def test_extract_finds_existing_source(self, client, user):
        client.force_login(user)
        src = CitationSource.objects.create(
            name="Learning Python", source_type="book", isbn="9780596517748"
        )
        resp = _post(client, EXTRACT_URL, {"input": "9780596517748"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["match"]["id"] == src.pk
        assert data["match"]["name"] == "Learning Python"
        assert data["match"]["skip_locator"] is False
        assert data["draft"] is None

    def test_extract_unsupported_input(self, client, user):
        client.force_login(user)
        resp = _post(client, EXTRACT_URL, {"input": "hello world"})
        assert resp.status_code == 422

    def test_extract_requires_auth(self, client):
        resp = _post(client, EXTRACT_URL, {"input": "9780596517748"})
        assert resp.status_code in (401, 403)

    def test_extract_rate_limit(self, client, user):
        cache.clear()
        client.force_login(user)
        CitationSource.objects.create(
            name="Learning Python", source_type="book", isbn="9780596517748"
        )

        for _ in range(10):
            resp = _post(client, EXTRACT_URL, {"input": "9780596517748"})
            assert resp.status_code == 200

        resp = _post(client, EXTRACT_URL, {"input": "9780596517748"})
        assert resp.status_code == 429

    @patch("apps.citation.api.extract_url")
    def test_extract_url_returns_draft(self, mock_extract, client, user):
        cache.clear()
        client.force_login(user)
        mock_extract.return_value = ExtractionResult(
            draft=ExtractionDraft(
                name="Pinball - Wikipedia",
                source_type="web",
                author="",
                publisher="Wikipedia",
                year=None,
                url="https://en.wikipedia.org/wiki/Pinball",
            ),
            confidence="low",
            source_api="og_meta",
        )
        resp = _post(
            client, EXTRACT_URL, {"input": "https://en.wikipedia.org/wiki/Pinball"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft"]["name"] == "Pinball - Wikipedia"
        assert data["draft"]["source_type"] == "web"
        assert data["draft"]["url"] == "https://en.wikipedia.org/wiki/Pinball"
        assert data["draft"]["publisher"] == "Wikipedia"
        assert data["confidence"] == "low"
        assert data["source_api"] == "og_meta"
        assert data["match"] is None

    @patch("apps.citation.api.extract_url")
    def test_extract_url_returns_match(self, mock_extract, client, user):
        cache.clear()
        client.force_login(user)
        mock_extract.return_value = ExtractionResult(
            match={"id": 42, "name": "IPDB #4836", "skip_locator": True}
        )
        resp = _post(
            client, EXTRACT_URL, {"input": "https://www.ipdb.org/machine.cgi?id=4836"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["match"]["id"] == 42
        assert data["match"]["name"] == "IPDB #4836"
        assert data["draft"] is None

    @patch("apps.citation.api.extract_url")
    def test_extract_url_returns_error(self, mock_extract, client, user):
        cache.clear()
        client.force_login(user)
        mock_extract.return_value = ExtractionResult(error="blocked")
        resp = _post(client, EXTRACT_URL, {"input": "http://localhost/admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "blocked"
        assert data["draft"] is None
        assert data["match"] is None

    def test_extract_url_classifies_correctly(self, client, user):
        """URL input no longer returns 422 (unsupported)."""
        cache.clear()
        client.force_login(user)
        with patch("apps.citation.api.extract_url") as mock_extract:
            mock_extract.return_value = ExtractionResult(error="timeout")
            resp = _post(client, EXTRACT_URL, {"input": "https://example.com"})
            assert resp.status_code == 200
            mock_extract.assert_called_once_with("https://example.com")
