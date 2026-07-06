"""Tests for deferred inline-citation minting on the claims save path.

The editor reserves a slug up front, places a ``[[cite:slug]]`` marker, and
sends the content spec in the save payload's ``inline_citations`` list; the
save handler mints the instance under that slug (consuming the reservation)
and rewrites the marker to storage form — all in the ChangeSet transaction.
Exercised end-to-end through PATCH /api/titles/{slug}/claims/.
"""

from __future__ import annotations

import json

import pytest

from apps.catalog.models import Title
from apps.citation.models import (
    CitationInstance,
    ReservedCitationSlug,
    reserve_citation_slug,
)
from apps.citation.test_factories import make_citation_source
from apps.core.types import JsonBody
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_claim

pytestmark = pytest.mark.django_db


@pytest.fixture
def title(db, bootstrap_source):
    t = Title.objects.create(
        name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4"
    )
    make_claim(t, "name", "Medieval Madness", ingest_source=bootstrap_source)
    return t


@pytest.fixture
def citation_source(db):
    return make_citation_source(name="Williams Flyer", source_type="web")


@pytest.fixture
def video_source(db):
    root = make_citation_source(
        name="YouTube", source_type="video", identifier_key="youtube"
    )
    return make_citation_source(
        name="YouTube #dQw4w9WgXcQ",
        source_type="video",
        parent=root,
        identifier="dQw4w9WgXcQ",
    )


def _patch(client, slug: str, body: JsonBody):
    return client.patch(
        f"/api/titles/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _spec(slug: str, source_id: int, locator: str = "", quote: str = "") -> JsonBody:
    return {
        "slug": slug,
        "citation_source_id": source_id,
        "locator": locator,
        "quote": quote,
    }


def _description_claim(title: Title) -> Claim:
    return Claim.objects.get(field_name="description", object_id=title.pk)


class TestInlineCitationMintAtSave:
    def test_mints_instance_and_rewrites_marker(
        self, client, user, title, citation_source
    ):
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"Great game.[[cite:{slug}]]"},
                "inline_citations": [
                    _spec(slug, citation_source.pk, "p. 3", "A wizard mode first.")
                ],
            },
        )
        assert resp.status_code == 200, resp.content

        instance = CitationInstance.objects.get(slug=slug)
        assert instance.citation_source_id == citation_source.pk
        assert instance.locator == "p. 3"
        assert instance.quote == "A wizard mode first."
        # The reservation was consumed in the same save.
        assert not ReservedCitationSlug.objects.filter(slug=slug).exists()
        # The stored claim value carries the storage-form marker.
        assert (
            _description_claim(title).value == f"Great game.[[cite:id:{instance.pk}]]"
        )
        # Inline instances are reachable through their marker alone: no join.
        assert instance.claims.count() == 0

    def test_repeated_marker_mints_one_instance(
        self, client, user, title, citation_source
    ):
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"A.[[cite:{slug}]] B.[[cite:{slug}]]"},
                "inline_citations": [_spec(slug, citation_source.pk)],
            },
        )
        assert resp.status_code == 200, resp.content
        instance = CitationInstance.objects.get(slug=slug)
        assert (
            _description_claim(title).value
            == f"A.[[cite:id:{instance.pk}]] B.[[cite:id:{instance.pk}]]"
        )

    def test_multiple_pending_cites_in_one_save(
        self, client, user, title, citation_source
    ):
        slug_a = reserve_citation_slug(user).slug
        slug_b = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"A.[[cite:{slug_a}]] B.[[cite:{slug_b}]]"},
                "inline_citations": [
                    _spec(slug_a, citation_source.pk, "p. 1"),
                    _spec(slug_b, citation_source.pk, "p. 2"),
                ],
            },
        )
        assert resp.status_code == 200, resp.content
        assert CitationInstance.objects.filter(slug__in=[slug_a, slug_b]).count() == 2
        assert ReservedCitationSlug.objects.count() == 0

    def test_existing_instance_marker_needs_no_spec(
        self, client, user, title, citation_source
    ):
        # A marker for an already-saved instance resolves as before — the
        # inline_citations list only covers cites new in this save.
        existing = CitationInstance.objects.create(
            citation_source=citation_source, locator="p. 9"
        )
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {"fields": {"description": f"Known.[[cite:{existing.slug}]]"}},
        )
        assert resp.status_code == 200, resp.content
        assert _description_claim(title).value == f"Known.[[cite:id:{existing.pk}]]"

    def test_video_locator_normalized_at_save(self, client, user, title, video_source):
        # The mint validates the locator against the cited source's
        # citation-type contract: a video timestamp is stored canonical.
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"See the demo.[[cite:{slug}]]"},
                "inline_citations": [_spec(slug, video_source.pk, "1h2m3s")],
            },
        )
        assert resp.status_code == 200, resp.content
        assert CitationInstance.objects.get(slug=slug).locator == "1:02:03"

    def test_invalid_video_locator_rejected(self, client, user, title, video_source):
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"See the demo.[[cite:{slug}]]"},
                "inline_citations": [_spec(slug, video_source.pk, "p. 42")],
            },
        )
        assert resp.status_code == 422
        # Nothing minted, reservation intact — the draft can be fixed and saved.
        assert not CitationInstance.objects.filter(slug=slug).exists()
        assert ReservedCitationSlug.objects.filter(slug=slug).exists()


class TestInlineCitationStrictness:
    def test_unknown_slug_rejected(self, client, user, title, citation_source):
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": "Great.[[cite:bcdbcdbc]]"},
                "inline_citations": [_spec("bcdbcdbc", citation_source.pk)],
            },
        )
        assert resp.status_code == 422
        assert "not a reserved slug" in resp.content.decode()

    def test_consumed_slug_rejected(self, client, user, title, citation_source):
        # The reservation was already consumed (instance exists): a stale or
        # replayed payload, strictly rejected.
        slug = reserve_citation_slug(user).slug
        CitationInstance.objects.create(citation_source=citation_source, slug=slug)
        ReservedCitationSlug.objects.filter(slug=slug).delete()
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"Great.[[cite:{slug}]]"},
                "inline_citations": [_spec(slug, citation_source.pk)],
            },
        )
        assert resp.status_code == 422
        assert "already been saved" in resp.content.decode()

    def test_foreign_reservation_rejected(self, client, user, title, citation_source):
        from apps.accounts.test_factories import make_user

        slug = reserve_citation_slug(make_user()).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"Great.[[cite:{slug}]]"},
                "inline_citations": [_spec(slug, citation_source.pk)],
            },
        )
        assert resp.status_code == 422
        assert "reserved by another user" in resp.content.decode()
        assert ReservedCitationSlug.objects.filter(slug=slug).exists()

    def test_unreferenced_spec_rejected_and_rolled_back(
        self, client, user, title, citation_source
    ):
        # The user deleted the marker text before saving (and the client
        # failed to prune the spec): minting it would create an orphan.
        # The whole save rolls back — no instance, reservation intact.
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": "No marker here."},
                "inline_citations": [_spec(slug, citation_source.pk)],
            },
        )
        assert resp.status_code == 422
        assert "not referenced" in resp.content.decode()
        assert not CitationInstance.objects.filter(slug=slug).exists()
        assert ReservedCitationSlug.objects.filter(slug=slug).exists()
        assert not Claim.objects.filter(
            field_name="description", object_id=title.pk
        ).exists()

    def test_duplicate_slugs_rejected(self, client, user, title, citation_source):
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"Great.[[cite:{slug}]]"},
                "inline_citations": [
                    _spec(slug, citation_source.pk, "p. 1"),
                    _spec(slug, citation_source.pk, "p. 2"),
                ],
            },
        )
        assert resp.status_code == 422
        assert "Duplicate" in resp.content.decode()

    def test_marker_without_spec_or_instance_rejected(self, client, user, title):
        # A dangling marker (no spec, no instance) still fails validation as
        # it always has — deferral applies only to slugs in the payload.
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {"fields": {"description": "Dangling.[[cite:bcdbcdbc]]"}},
        )
        assert resp.status_code == 422

    def test_unknown_source_rejected(self, client, user, title):
        slug = reserve_citation_slug(user).slug
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": f"Great.[[cite:{slug}]]"},
                "inline_citations": [_spec(slug, 999_999)],
            },
        )
        assert resp.status_code == 422
        assert ReservedCitationSlug.objects.filter(slug=slug).exists()
