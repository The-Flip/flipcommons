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
from apps.citation.test_factories import (
    make_citation_link,
    make_citation_root_domain,
    make_citation_source,
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
            make_citation_source(name=f"Test Source {i}", source_type="book")
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
        make_citation_source(
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
        parent = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        child = make_citation_source(
            name="IPDB #4443",
            source_type="web",
            parent=parent,
            identifier="4443",
        )
        make_citation_link(
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
        make_citation_source(name="IPDB", source_type="web", identifier_key="ipdb")
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
        jjp = make_citation_source(name="Jersey Jack Pinball", source_type="web")
        make_citation_root_domain(source=jjp, host="jerseyjackpinball.com")
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
        parent = make_citation_source(name="Jersey Jack Pinball", source_type="web")
        make_citation_link(
            citation_source=parent,
            link_type="homepage",
            url="https://www.jerseyjackpinball.com/",
        )
        child = make_citation_source(
            name="Elton John Pinball", source_type="web", parent=parent
        )
        url = "https://jerseyjackpinball.com/products/elton-john"
        make_citation_link(citation_source=child, link_type="homepage", url=url)
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

    def test_malformed_host_url_no_recognition(self, client, user, db):
        """A malformed host whose ancestor suffix matches a seeded root still
        yields no recognition — /search/ must not surface a confident-but-wrong
        page for garbage input (the read surface has no write-time URL guard)."""
        root = make_citation_source(name="American Pinball", source_type="web")
        make_citation_root_domain(source=root, host="american-pinball.com")
        client.force_login(user)
        resp = client.get(
            "/api/citation-sources/search/?q=https://www..american-pinball.com/m.pdf"
        )
        assert resp.json()["recognition"] is None

    def test_plain_text_no_recognition(self, client, user, citation_source):
        """Plain text searches return no recognition."""
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Encyclopedia")
        data = resp.json()
        assert data["recognition"] is None
        assert len(data["results"]) >= 1

    def test_subdomain_resolves_to_most_specific_root(self, client, user, db):
        """twip.kineticist.com resolves to the TWiP root, not kineticist.com."""
        kineticist = make_citation_source(name="Kineticist", source_type="web")
        make_citation_root_domain(source=kineticist, host="kineticist.com")
        twip = make_citation_source(name="TWiP", source_type="web")
        make_citation_root_domain(source=twip, host="twip.kineticist.com")
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
        source = make_citation_source(name="Some Source", source_type="web")
        make_citation_link(
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
        make_citation_source(name="Solo Book", source_type="book")
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Solo Book")
        data = resp.json()["results"][0]
        assert data["is_abstract"] is False
        assert data["skip_locator"] is False

    def test_root_book_with_children(self, client, user, db):
        """A book with editions: abstract."""
        parent = make_citation_source(name="Big Book", source_type="book")
        make_citation_source(name="Big Book Ed. 1", source_type="book", parent=parent)
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Big Book")
        results = {r["id"]: r for r in resp.json()["results"]}
        data = results[parent.pk]
        assert data["is_abstract"] is True
        assert data["skip_locator"] is False

    def test_root_web_source(self, client, user, db):
        """A root web source (e.g. IPDB): abstract."""
        make_citation_source(
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
        make_citation_source(name="Jersey Jack Pinball", source_type="web")
        client.force_login(user)
        resp = client.get("/api/citation-sources/search/?q=Jersey Jack")
        data = resp.json()["results"][0]
        assert data["is_abstract"] is True
        assert data["skip_locator"] is False

    def test_child_web_source(self, client, user, db):
        """A child web source (e.g. IPDB machine page): skip locator."""
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        child = make_citation_source(
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
        make_citation_source(name="Pinball Magazine", source_type="magazine")
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
        assert source.created_by == user.actor
        assert source.updated_by == user.actor

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


class TestCreateCitationSourceForbidsMovedFields:
    """The god-endpoint creates plain authored sources only.

    URLs/links moved to ``cite-url``/``pages/`` and scheme identifiers to
    ``records/``; ``extra="forbid"`` + the ``source_type`` Literal make every
    moved field a 422 here. Body shape isn't asserted — the forbid 422 takes the
    global pydantic-handler path, not the endpoint's declared error schema.
    """

    def test_authored_child_is_linkless(self, client, user, citation_source):
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
        assert resp.json()["links"] == []

    def test_url_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {"name": "X", "source_type": "book", "url": "https://example.com/"},
        )
        assert resp.status_code == 422

    def test_link_type_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {"name": "X", "source_type": "book", "link_type": "homepage"},
        )
        assert resp.status_code == 422

    def test_link_label_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {"name": "X", "source_type": "book", "link_label": "label"},
        )
        assert resp.status_code == 422

    def test_identifier_returns_422(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {"name": "X", "source_type": "book", "identifier": "4443"},
        )
        assert resp.status_code == 422

    def test_web_source_type_returns_422(self, client, user):
        # Web roots/children are born from cite-url/pages/, never the plain path —
        # a web child here would be skip_locator with neither locator nor URL.
        client.force_login(user)
        resp = _post(
            client,
            "/api/citation-sources/",
            {"name": "X", "source_type": "web"},
        )
        assert resp.status_code == 422


class TestCiteUrl:
    """The interactive web-create finalize endpoint, ``POST /cite-url/``."""

    URL = "/api/citation-sources/cite-url/"

    def test_anonymous_gets_401(self, client):
        resp = _post(client, self.URL, {"url": "https://example.com/page"})
        assert resp.status_code in (401, 403)

    def test_no_match_rounds_to_registrable_root_and_creates_child(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            self.URL,
            {
                "url": "https://blog.newsite.org/post",
                "site_name": "New Site",
                "site_description": "A site.",
                "page_name": "A Post",
            },
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.name == "A Post"
        assert child.parent is not None
        # The funnel rounds the fuzzy subdomain paste down to the registrable
        # domain, so the root (and its homepage) sit at newsite.org — future
        # cites under any subdomain collapse to this one root.
        root = child.parent
        assert root.name == "New Site"
        assert root.description == "A site."
        assert root.parent_id is None
        domain = CitationSourceRootDomain.objects.get(source=root)
        assert domain.host == "newsite.org"
        assert root.links.get(link_type="homepage").url == "https://newsite.org/"
        # The child still references the full pasted URL, not the rounded host.
        assert child.links.get(link_type="reference").url == (
            "https://blog.newsite.org/post"
        )

    def test_no_match_attributes_every_row_to_caller(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            self.URL,
            {"url": "https://newsite.org/x", "page_name": "X"},
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        root = child.parent
        assert root is not None
        assert child.created_by == user.actor
        assert child.updated_by == user.actor
        assert root.created_by == user.actor
        assert root.updated_by == user.actor
        for link in CitationSourceLink.objects.filter(
            citation_source__in=[root, child]
        ):
            assert link.created_by == user.actor
            assert link.updated_by == user.actor
        # The minted recognition domain is attributed too — it is a row the
        # caller's action created, same as the source and its links.
        domain = CitationSourceRootDomain.objects.get(source=root)
        assert domain.created_by == user.actor
        assert domain.updated_by == user.actor

    def test_blank_site_name_falls_back_to_rounded_host(self, client, user):
        client.force_login(user)
        resp = _post(client, self.URL, {"url": "https://blog.newsite.org/p"})
        assert resp.status_code == 201
        root = CitationSource.objects.get(pk=resp.json()["id"]).parent
        assert root is not None
        # Falls back to the rounded registrable host, not the raw subdomain.
        assert root.name == "newsite.org"

    def test_response_is_the_web_child(self, client, user):
        client.force_login(user)
        resp = _post(
            client, self.URL, {"url": "https://newsite.org/p", "page_name": "P"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "P"
        # A web child skips the locator stage — its URL is the locator.
        assert data["skip_locator"] is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/page",  # IP literal — can't root a site
            "http://foo.test/page",  # reserved RFC special-use TLD
            "https://gov.uk/page",  # bare public suffix — over-matches if stored
            "https://[::1/page",  # malformed URL — must 422, not 500
        ],
    )
    def test_unroundable_host_is_422_with_no_write(self, client, user, url):
        client.force_login(user)
        resp = _post(client, self.URL, {"url": url})
        assert resp.status_code == 422
        # The funnel rejects before any write, so nothing was created.
        assert not CitationSource.objects.exists()
        assert not CitationSourceRootDomain.objects.exists()

    def test_domain_match_nests_child_and_ignores_site_fields(self, client, user):
        client.force_login(user)
        root = make_citation_source(name="Existing", source_type="web")
        make_citation_root_domain(source=root, host="existing.example")
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
        assert child.created_by == user.actor
        assert child.updated_by == user.actor
        ref = child.links.get(link_type="reference")
        assert ref.created_by == user.actor
        assert ref.updated_by == user.actor
        # The root is never renamed/redescribed from here.
        root.refresh_from_db()
        assert root.name == "Existing"
        assert root.description == ""
        # No second root was created.
        assert CitationSource.objects.filter(parent__isnull=True).count() == 1

    def test_subdomain_nests_under_existing_registrable_root(self, client, user):
        # Suffix matching: an asset subdomain resolves to the seeded registrable
        # root, so the cite nests a child *under* american-pinball.com rather
        # than minting a second root.
        client.force_login(user)
        root = make_citation_source(name="American Pinball", source_type="web")
        make_citation_root_domain(source=root, host="american-pinball.com")
        resp = _post(
            client,
            self.URL,
            {"url": "https://s4.american-pinball.com/manual.pdf"},
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.parent_id == root.pk
        # No second root was minted.
        assert CitationSource.objects.filter(parent__isnull=True).count() == 1
        # No page_name sent → the child name falls back to the URL.
        assert child.name == "https://s4.american-pinball.com/manual.pdf"

    def test_exact_child_is_reused(self, client, user):
        client.force_login(user)
        root = make_citation_source(name="Existing", source_type="web")
        make_citation_root_domain(source=root, host="existing.example")
        child = make_citation_source(name="Page", source_type="web", parent=root)
        make_citation_link(
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
        make_citation_source(name="IPDB", source_type="web", identifier_key="ipdb")
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
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        child = make_citation_source(
            name="IPDB #4443", source_type="web", parent=root, identifier="4443"
        )
        make_citation_link(
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
        """A domain-model guard failure surfaces as the declared 422 and rolls back.

        The root-domain row is ``full_clean``d in its own ``try/except`` so a
        model guard (the public-suffix / DNS-host ``clean()`` rules) becomes a
        422 rather than a 500 — Django's ``ValidationError`` has no API exception
        handler, so an uncaught one would 500. We force ``full_clean`` to raise
        to exercise that wrapper directly, decoupled from any specific rule. The
        URL uses a real registrable domain so the ``root_host_from_url`` funnel
        passes and the mocked ``full_clean`` actually fires; the whole create
        then rolls back.
        """
        client.force_login(user)

        def reject(self, *args, **kwargs):
            raise ValidationError({"host": "Not an allowed recognition host."})

        with patch.object(CitationSourceRootDomain, "full_clean", reject):
            resp = _post(client, self.URL, {"url": "https://blocked.org/p"})
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
        racer = make_citation_source(name="Racer", source_type="web")

        def raise_integrity(self, *args, **kwargs):
            raise IntegrityError("duplicate key value violates unique constraint")

        rematch = Recognition(parent_id=racer.pk, parent_name="Racer")
        with (
            patch.object(CitationSourceRootDomain, "save", raise_integrity),
            patch("apps.citation.api.recognize_url", side_effect=[None, rematch]),
        ):
            resp = _post(
                client, self.URL, {"url": "https://raced.org/p", "page_name": "P"}
            )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        # Nested under the racer's root, not a duplicate, no 500.
        assert child.parent_id == racer.pk
        assert CitationSource.objects.filter(name="P").count() == 1
        # The savepoint rolled back the attempted root + its homepage link (blank
        # site_name → it was named after the rounded host), leaving only the
        # racer root.
        assert not CitationSource.objects.filter(name="raced.org").exists()
        assert CitationSource.objects.filter(parent__isnull=True).count() == 1


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
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        child = make_citation_source(
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
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        make_citation_source(name="IPDB Machine 2000", source_type="web", parent=parent)
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/")
        data = resp.json()
        assert len(data["children"]) == 1
        assert data["children"][0]["skip_locator"] is True

    def test_detail_children_include_urls(self, client, user, db):
        """Children in detail response include their link URLs."""
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        child = make_citation_source(
            name="IPDB Machine 3000", source_type="web", parent=parent
        )
        make_citation_link(
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
        parent = make_citation_source(name="Big Book", source_type="book")
        make_citation_source(name="Edition 1", source_type="book", parent=parent)
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
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        make_citation_source(name="IPDB Machine 1000", source_type="web", parent=parent)
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/children/?q=")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_filter_by_child_name(self, client, user, db):
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        match = make_citation_source(
            name="IPDB Machine 4836", source_type="web", parent=parent
        )
        make_citation_source(name="IPDB Machine 9999", source_type="web", parent=parent)
        client.force_login(user)
        resp = client.get(f"/api/citation-sources/{parent.pk}/children/?q=4836")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["id"] == match.pk

    def test_filter_by_child_url(self, client, user, db):
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        child = make_citation_source(
            name="IPDB Machine 4836", source_type="web", parent=parent
        )
        make_citation_link(
            citation_source=child,
            link_type="homepage",
            url="https://www.ipdb.org/machine.cgi?id=4836",
        )
        make_citation_source(name="IPDB Machine 9999", source_type="web", parent=parent)
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
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        child = make_citation_source(
            name="IPDB Machine 5000", source_type="web", parent=parent, year=2020
        )
        make_citation_link(
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
        parent = make_citation_source(
            name="Internet Pinball Database", source_type="web"
        )
        for i in range(25):
            make_citation_source(
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
        assert citation_source.updated_by == user.actor

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
        other = make_citation_source(
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
        source = make_citation_source(name="Test", source_type="book", year=1996)
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
        assert link.created_by == user.actor
        assert link.updated_by == user.actor

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
        assert citation_source_link.updated_by == user.actor

    def test_link_on_wrong_source_returns_404(self, client, user, citation_source_link):
        other_source = make_citation_source(name="Other", source_type="web")
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
        make_citation_link(
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
        src = make_citation_source(
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
        make_citation_source(
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
        """URL input is classified and routed to extract_url, not rejected as 422."""
        cache.clear()
        client.force_login(user)
        with patch("apps.citation.api.extract_url") as mock_extract:
            mock_extract.return_value = ExtractionResult(error="timeout")
            resp = _post(client, EXTRACT_URL, {"input": "https://example.com"})
            assert resp.status_code == 200
            mock_extract.assert_called_once_with("https://example.com")


# ---------------------------------------------------------------------------
# Nested child-mint endpoints: pages/ and records/
# ---------------------------------------------------------------------------


class TestCreateCitationSourcePage:
    """``POST /{source_id}/pages/`` — mint a web page child under a chosen root."""

    @staticmethod
    def _url(parent_id):
        return f"/api/citation-sources/{parent_id}/pages/"

    def test_anonymous_gets_401(self, client):
        root = make_citation_source(name="Site", source_type="web")
        resp = _post(client, self._url(root.pk), {"url": "https://site.example/p"})
        assert resp.status_code in (401, 403)

    def test_mints_validated_attributed_child(self, client, user):
        # pages/ files directly under the chosen parent — no recognition, so the
        # root needs no recognition domain.
        client.force_login(user)
        root = make_citation_source(name="Site", source_type="web")
        resp = _post(
            client,
            self._url(root.pk),
            {"url": "https://site.example/article", "page_name": "Article"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Article"
        # A web child skips the locator stage — its URL is the locator.
        assert data["skip_locator"] is True
        child = CitationSource.objects.get(pk=data["id"])
        assert child.parent_id == root.pk
        assert child.created_by == user.actor
        assert child.updated_by == user.actor
        ref = child.links.get(link_type="reference")
        assert ref.url == "https://site.example/article"
        assert ref.created_by == user.actor

    def test_blank_page_name_falls_back_to_url(self, client, user):
        client.force_login(user)
        root = make_citation_source(name="Site", source_type="web")
        resp = _post(client, self._url(root.pk), {"url": "https://site.example/x"})
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.name == "https://site.example/x"

    def test_accepts_page_under_magazine_root(self, client, user):
        # pages/ doesn't restrict the parent's type — a web page under a
        # magazine/book root is intended (the live "Pinball Magazine" magazine
        # root has web children). Pin it so a future "web-only" guard can't land.
        client.force_login(user)
        root = make_citation_source(name="Pinball Magazine", source_type="magazine")
        resp = _post(
            client,
            self._url(root.pk),
            {"url": "https://pinball-magazine.example/post", "page_name": "Post"},
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.parent_id == root.pk
        assert child.source_type == "web"

    def test_missing_parent_returns_404(self, client, user):
        client.force_login(user)
        resp = _post(client, self._url(999999), {"url": "https://site.example/p"})
        assert resp.status_code == 404

    def test_page_under_web_child_parent_returns_422(self, client, user):
        # The web-flatness guard: a web child's parent must be a root, so a
        # page nested under a web child (a grandchild) is rejected by clean().
        client.force_login(user)
        root = make_citation_source(name="Site", source_type="web")
        child = make_citation_source(name="Page", source_type="web", parent=root)
        resp = _post(client, self._url(child.pk), {"url": "https://site.example/deep"})
        assert resp.status_code == 422

    def test_malformed_url_returns_422(self, client, user):
        client.force_login(user)
        root = make_citation_source(name="Site", source_type="web")
        resp = _post(client, self._url(root.pk), {"url": "not-a-url"})
        assert resp.status_code == 422

    def test_extra_field_returns_422(self, client, user):
        client.force_login(user)
        root = make_citation_source(name="Site", source_type="web")
        resp = _post(
            client,
            self._url(root.pk),
            {"url": "https://site.example/p", "source_type": "web"},
        )
        assert resp.status_code == 422


class TestCreateCitationSourceRecord:
    """``POST /{source_id}/records/`` — mint/reuse a scheme child under a root."""

    @staticmethod
    def _url(parent_id):
        return f"/api/citation-sources/{parent_id}/records/"

    def test_anonymous_gets_401(self, client):
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(client, self._url(root.pk), {"identifier": "4443"})
        assert resp.status_code in (401, 403)

    def test_mints_validated_attributed_child(self, client, user):
        client.force_login(user)
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(client, self._url(root.pk), {"identifier": "4443"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "IPDB #4443"
        child = CitationSource.objects.get(pk=data["id"])
        assert child.parent_id == root.pk
        assert child.identifier == "4443"
        assert child.created_by == user.actor
        ref = child.links.get(link_type="reference")
        assert ref.url == "https://www.ipdb.org/machine.cgi?id=4443"

    def test_recite_existing_identifier_reuses_child(self, client, user):
        client.force_login(user)
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        first = _post(client, self._url(root.pk), {"identifier": "4443"})
        second = _post(client, self._url(root.pk), {"identifier": "4443"})
        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]
        assert CitationSource.objects.filter(parent=root).count() == 1

    def test_pasted_url_normalized_to_bare_id(self, client, user):
        client.force_login(user)
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(
            client,
            self._url(root.pk),
            {"identifier": "https://www.ipdb.org/machine.cgi?id=4443"},
        )
        assert resp.status_code == 201
        child = CitationSource.objects.get(pk=resp.json()["id"])
        assert child.identifier == "4443"

    def test_missing_parent_returns_404(self, client, user):
        client.force_login(user)
        resp = _post(client, self._url(999999), {"identifier": "4443"})
        assert resp.status_code == 404

    def test_parent_without_scheme_returns_422(self, client, user):
        # A parent root that carries no identifier_key has no scheme; the leaf
        # raises ValueError, which must surface as a 422 (not a 500).
        client.force_login(user)
        root = make_citation_source(name="Some Site", source_type="web")
        resp = _post(client, self._url(root.pk), {"identifier": "4443"})
        assert resp.status_code == 422

    def test_invalid_identifier_returns_422(self, client, user):
        client.force_login(user)
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(client, self._url(root.pk), {"identifier": "abc"})
        assert resp.status_code == 422

    def test_random_url_as_identifier_returns_422(self, client, user):
        # A non-IPDB URL doesn't match the extractor's format → rejected.
        client.force_login(user)
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(
            client, self._url(root.pk), {"identifier": "https://example.com/page"}
        )
        assert resp.status_code == 422

    def test_overlong_generated_name_returns_422(self, client, user):
        # A max-length root name + identifier overflows the generated child name;
        # the leaf's full_clean ValidationError must map to a 422, not a 500.
        client.force_login(user)
        root = make_citation_source(
            name="X" * 500, source_type="web", identifier_key="ipdb"
        )
        resp = _post(client, self._url(root.pk), {"identifier": "1"})
        assert resp.status_code == 422

    def test_extra_field_returns_422(self, client, user):
        client.force_login(user)
        root = make_citation_source(
            name="IPDB", source_type="web", identifier_key="ipdb"
        )
        resp = _post(
            client,
            self._url(root.pk),
            {"identifier": "4443", "source_type": "web"},
        )
        assert resp.status_code == 422
