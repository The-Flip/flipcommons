"""Tests for the citation-instances API endpoint."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.citation.models import (
    CitationInstance,
    ReservedCitationSlug,
    validate_citation_slug,
)
from apps.citation.test_factories import make_citation_link, make_citation_source
from apps.provenance.test_factories import (
    cite_claim,
    claim_citation_instance,
    make_citation_instance,
    make_claim,
    make_ingest_source,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def citation_source(db):
    return make_citation_source(
        name="The Encyclopedia of Pinball",
        source_type="book",
    )


VIDEO_ID = "dQw4w9WgXcQ"
VIDEO_CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.fixture
def video_source(db):
    """A youtube video child under its scheme root."""
    root = make_citation_source(
        name="YouTube", source_type="video", identifier_key="youtube"
    )
    return make_citation_source(
        name=f"YouTube #{VIDEO_ID}",
        source_type="video",
        parent=root,
        identifier=VIDEO_ID,
    )


class TestListCitationInstances:
    def test_anonymous_gets_401(self, client):
        resp = client.get("/api/citation-instances/?source=1")
        assert resp.status_code in (401, 403)

    def test_no_filter_returns_422(self, client, user):
        client.force_login(user)
        resp = client.get("/api/citation-instances/")
        assert resp.status_code == 422

    def test_filter_by_source(self, client, user, citation_source):
        ci = make_citation_instance(citation_source=citation_source, locator="p. 30")
        client.force_login(user)
        resp = client.get(f"/api/citation-instances/?source={citation_source.pk}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == ci.pk
        assert data[0]["locator"] == "p. 30"
        assert data[0]["citation_source_name"] == citation_source.name

    def test_filter_by_claim(self, client, user, citation_source):
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        claim = make_claim(mfr, "name", "Williams", ingest_source=make_ingest_source())

        ci = cite_claim(claim, citation_source=citation_source, locator="p. 42")
        client.force_login(user)
        resp = client.get(f"/api/citation-instances/?claim={claim.pk}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == ci.pk

    def test_filter_by_claim_reads_the_join(self, client, user, citation_source):
        """``?claim=`` resolves through the ClaimCitationInstance join: a
        linked instance is returned; an unlinked one is not."""
        from apps.catalog.models import Manufacturer

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        claim = make_claim(mfr, "name", "Williams", ingest_source=make_ingest_source())

        linked = make_citation_instance(
            citation_source=citation_source, locator="p. 42"
        )
        claim_citation_instance(claim, linked)
        make_citation_instance(citation_source=citation_source, locator="p. 7")

        client.force_login(user)
        resp = client.get(f"/api/citation-instances/?claim={claim.pk}")
        assert resp.status_code == 200
        assert [item["id"] for item in resp.json()] == [linked.pk]

    def test_empty_result(self, client, user, citation_source):
        client.force_login(user)
        resp = client.get(f"/api/citation-instances/?source={citation_source.pk}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_response_shape(self, client, user, citation_source):
        make_citation_instance(citation_source=citation_source, locator="front")
        client.force_login(user)
        resp = client.get(f"/api/citation-instances/?source={citation_source.pk}")
        data = resp.json()[0]
        assert set(data.keys()) == {
            "id",
            "slug",
            "citation_source_id",
            "citation_source_name",
            "locator",
            "quote",
            "created_at",
        }


class TestBatchCitationInstances:
    def test_returns_instances_with_source_details(self, client, citation_source):
        ci = make_citation_instance(
            citation_source=citation_source,
            locator="p. 30",
            quote="A masterpiece of the solid-state era.",
        )
        make_citation_link(
            citation_source=citation_source,
            link_type="archive",
            url="https://archive.org/details/example",
            label="archive.org scan",
        )
        resp = client.get(f"/api/citation-instances/batch/?ids={ci.pk}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["id"] == ci.pk
        assert item["source_name"] == "The Encyclopedia of Pinball"
        assert item["source_type"] == "book"
        assert item["locator"] == "p. 30"
        assert item["quote"] == "A masterpiece of the solid-state era."
        assert len(item["links"]) == 1
        assert item["links"][0]["url"] == "https://archive.org/details/example"
        assert item["links"][0]["link_type"] == "archive"
        assert item["links"][0]["display_name"] == "archive.org scan"

    def test_link_display_name_falls_back_to_link_type(self, client, citation_source):
        ci = make_citation_instance(citation_source=citation_source, locator="p. 30")
        make_citation_link(
            citation_source=citation_source,
            link_type="reference",
            url="https://example.com/unlabeled",
            label="",
        )
        resp = client.get(f"/api/citation-instances/batch/?ids={ci.pk}")
        assert resp.status_code == 200
        link = resp.json()[0]["links"][0]
        assert link["display_name"] == "Reference"

    def test_multiple_ids(self, client, citation_source):
        ci1 = make_citation_instance(citation_source=citation_source, locator="p. 30")
        ci2 = make_citation_instance(citation_source=citation_source, locator="p. 83")
        resp = client.get(f"/api/citation-instances/batch/?ids={ci1.pk},{ci2.pk}")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()}
        assert ids == {ci1.pk, ci2.pk}

    def test_empty_ids_returns_empty_list(self, client, db):
        resp = client.get("/api/citation-instances/batch/?ids=")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_nonexistent_ids_skipped(self, client, citation_source):
        ci = make_citation_instance(citation_source=citation_source, locator="p. 1")
        resp = client.get(f"/api/citation-instances/batch/?ids={ci.pk},99999")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == ci.pk

    def test_no_auth_required(self, client, citation_source):
        ci = make_citation_instance(citation_source=citation_source, locator="p. 1")
        # No force_login — anonymous request
        resp = client.get(f"/api/citation-instances/batch/?ids={ci.pk}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_response_shape(self, client, citation_source):
        make_citation_instance(citation_source=citation_source, locator="front")
        instance = CitationInstance.objects.first()
        assert instance is not None
        resp = client.get(f"/api/citation-instances/batch/?ids={instance.pk}")
        data = resp.json()[0]
        assert set(data.keys()) == {
            "id",
            "source_name",
            "root_name",
            "source_type",
            "author",
            "year",
            "locator",
            "quote",
            "links",
        }

    def test_root_name_is_null_for_a_root_source(self, client, citation_source):
        make_citation_instance(citation_source=citation_source, locator="front")
        instance = CitationInstance.objects.first()
        assert instance is not None
        resp = client.get(f"/api/citation-instances/batch/?ids={instance.pk}")
        assert resp.json()[0]["root_name"] is None

    def test_root_name_names_the_parent_for_a_child_source(self, client, db):
        periodical = make_citation_source(
            name="GameRoom Magazine", source_type="periodical"
        )
        issue = make_citation_source(
            name="Vol. 10 No. 6, March 1994",
            source_type="periodical",
            parent=periodical,
        )
        ci = make_citation_instance(citation_source=issue, locator="p. 42")
        resp = client.get(f"/api/citation-instances/batch/?ids={ci.pk}")
        data = resp.json()[0]
        assert data["source_name"] == "Vol. 10 No. 6, March 1994"
        assert data["root_name"] == "GameRoom Magazine"

    def test_caps_at_50_ids(self, client, db):
        ids = ",".join(str(i) for i in range(1, 52))
        resp = client.get(f"/api/citation-instances/batch/?ids={ids}")
        assert resp.status_code == 422

    def test_video_link_is_deep_linked_to_the_locator(self, client, video_source):
        # Server-computed deep links: the canonical video link ships pointing
        # at the cited moment; the frontend renders, never builds.
        make_citation_link(
            citation_source=video_source, link_type="reference", url=VIDEO_CANONICAL
        )
        ci = make_citation_instance(citation_source=video_source, locator="1:35")
        resp = client.get(f"/api/citation-instances/batch/?ids={ci.pk}")
        assert resp.status_code == 200
        assert resp.json()[0]["links"][0]["url"] == f"{VIDEO_CANONICAL}&t=95s"


class TestReserveCitationSlug:
    def test_reserve(self, client, user):
        client.force_login(user)
        resp = client.post("/api/citation-instances/reservations/")
        assert resp.status_code == 201
        slug = resp.json()["slug"]
        validate_citation_slug(slug)
        reservation = ReservedCitationSlug.objects.get(slug=slug)
        assert reservation.created_by == user

    def test_each_reservation_is_fresh(self, client, user):
        client.force_login(user)
        first = client.post("/api/citation-instances/reservations/").json()["slug"]
        second = client.post("/api/citation-instances/reservations/").json()["slug"]
        assert first != second
        assert ReservedCitationSlug.objects.count() == 2

    def test_anonymous_gets_401(self, client):
        resp = client.post("/api/citation-instances/reservations/")
        assert resp.status_code in (401, 403)
