"""Tests for PATCH /api/titles/{public_id}/claims/."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Franchise, Title
from apps.catalog.resolve import resolve_all_entities
from apps.catalog.resolve._relationships import resolve_all_title_abbreviations
from apps.citation.models import CitationSource
from apps.core.types import JsonBody
from apps.provenance.claims import build_relationship_claim
from apps.provenance.models import ChangeSet, Claim, Source
from apps.provenance.test_factories import make_claim, user_changeset

User = get_user_model()


@pytest.fixture
def title(db, _bootstrap_source):
    t = Title.objects.create(
        name="Medieval Madness", slug="medieval-madness", opdb_id="G5pe4"
    )
    make_claim(t, "name", "Medieval Madness", source=_bootstrap_source)
    return t


@pytest.fixture
def franchise(db):
    return Franchise.objects.create(name="Castle Games", slug="castle-games")


@pytest.fixture
def other_franchise(db):
    return Franchise.objects.create(name="Remake Line", slug="remake-line")


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="IPDB", slug="ipdb", source_type="database", priority=10
    )


@pytest.fixture
def citation_source(db):
    return CitationSource.objects.create(name="Williams Flyer", source_type="web")


def _patch(client, slug: str, body: JsonBody):
    return client.patch(
        f"/api/titles/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


def _assert_title_abbreviations(
    title: Title, source: Source, values: list[str]
) -> None:
    for value in values:
        claim_key, claim_value = build_relationship_claim(
            "abbreviation", {"value": value}
        )
        make_claim(
            title,
            "abbreviation",
            claim_value,
            source=source,
            claim_key=claim_key,
        )
    resolve_all_entities(Title, object_ids={title.pk})
    resolve_all_title_abbreviations(subject_ids={title.pk})


@pytest.mark.django_db
class TestPatchTitleClaims:
    def test_anonymous_gets_401(self, client, title):
        resp = _patch(client, title.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code in (401, 403)

    def test_nonexistent_slug_returns_404(self, client, user):
        client.force_login(user)
        resp = _patch(client, "does-not-exist", {"fields": {"name": "Updated"}})
        assert resp.status_code == 404

    def test_empty_changes_returns_422(self, client, user, title):
        client.force_login(user)
        resp = _patch(client, title.slug, {"fields": {}})
        assert resp.status_code == 422

    def test_scalar_edit_updates_title_and_returns_sources(
        self, client, user, title, franchise
    ):
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {
                    "name": "Medieval Madness Remastered",
                    "description": "Updated title copy",
                    "franchise": franchise.slug,
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Medieval Madness Remastered"
        assert data["description"]["text"] == "Updated title copy"
        assert data["franchise"]["public_id"] == franchise.public_id

        title.refresh_from_db()
        assert title.name == "Medieval Madness Remastered"
        assert title.description == "Updated title copy"
        assert title.franchise == franchise

    def test_slug_can_be_changed(self, client, user, title):
        client.force_login(user)
        resp = _patch(
            client, title.slug, {"fields": {"slug": "medieval-madness-remastered"}}
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "medieval-madness-remastered"

        title.refresh_from_db()
        assert title.slug == "medieval-madness-remastered"
        assert client.get(f"/api/pages/title/{title.slug}").status_code == 200
        assert client.get("/api/pages/title/medieval-madness").status_code == 404

    def test_duplicate_slug_returns_422(self, client, user, title):
        Title.objects.create(name="Attack from Mars", slug="attack-from-mars")
        client.force_login(user)
        resp = _patch(client, title.slug, {"fields": {"slug": "attack-from-mars"}})
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()

    def test_franchise_can_be_changed_and_cleared(
        self, client, user, title, franchise, other_franchise
    ):
        client.force_login(user)

        resp = _patch(
            client,
            title.slug,
            {"fields": {"franchise": franchise.slug}},
        )
        assert resp.status_code == 200
        assert resp.json()["franchise"]["public_id"] == franchise.public_id

        resp = _patch(
            client,
            title.slug,
            {"fields": {"franchise": other_franchise.slug}},
        )
        assert resp.status_code == 200
        assert resp.json()["franchise"]["public_id"] == other_franchise.public_id

        resp = _patch(
            client,
            title.slug,
            {"fields": {"franchise": None}},
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["franchise"] is None

    def test_abbreviations_can_be_added(self, client, user, title):
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {"abbreviations": ["MM", "MMR"]},
        )
        assert resp.status_code == 200
        assert resp.json()["abbreviations"] == ["MM", "MMR"]

    def test_abbreviations_can_be_removed(self, client, user, title, source):
        _assert_title_abbreviations(title, source, ["MM", "MMR"])
        client.force_login(user)

        resp = _patch(
            client,
            title.slug,
            {"abbreviations": ["MMR"]},
        )
        assert resp.status_code == 200
        assert resp.json()["abbreviations"] == ["MMR"]

    def test_abbreviations_can_be_replaced_atomically(
        self, client, user, title, source
    ):
        _assert_title_abbreviations(title, source, ["MM", "TAF"])
        client.force_login(user)

        resp = _patch(
            client,
            title.slug,
            {"abbreviations": ["MM", "CC"]},
        )
        assert resp.status_code == 200
        assert resp.json()["abbreviations"] == ["CC", "MM"]

    def test_scalar_and_abbreviation_edits_share_one_changeset(
        self, client, user, title
    ):
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": "Fresh copy"},
                "abbreviations": ["MM", "MMR"],
                "note": "Grouped title edit",
            },
        )
        assert resp.status_code == 200

        # The title fixture asserts a seed (ingest) name claim, so filter to the
        # user's changeset rather than assuming it's the only row.
        assert ChangeSet.objects.filter(user=user).count() == 1
        changeset = ChangeSet.objects.get(user=user)
        assert changeset.note == "Grouped title edit"
        assert changeset.claims.count() == 3
        assert {claim.field_name for claim in changeset.claims.all()} == {
            "description",
            "abbreviation",
        }

    def test_changeset_note_is_returned_in_sources(self, client, user, title):
        client.force_login(user)
        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": "Updated"},
                "abbreviations": ["MM"],
                "note": "Editorial cleanup",
            },
        )
        assert resp.status_code == 200
        sources_resp = client.get(f"/api/pages/sources/title/{title.slug}/")
        assert any(
            claim["changeset_note"] == "Editorial cleanup"
            for claim in sources_resp.json()["sources"]
        )

    def test_scalar_edit_with_citation_clones_to_created_claim(
        self, client, user, title, citation_source
    ):
        client.force_login(user)
        template_claim = make_claim(
            title,
            "description",
            "Template citation seed",
            user=user,
            changeset=user_changeset(user, note="seed"),
        )
        template_instance = citation_source.instances.create(
            claim=template_claim,
            locator="p. 2",
        )

        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": "Updated"},
                "citation": {"citation_instance_id": template_instance.pk},
            },
        )

        assert resp.status_code == 200, resp.json()
        assert template_claim.changeset_id is not None
        # Restrict to the editing user's changesets (the title fixture's seed name
        # claim is ingest) and exclude the citation-template seed changeset.
        changeset = (
            ChangeSet.objects.filter(user=user)
            .exclude(pk=template_claim.changeset_id)
            .get()
        )
        created_claim = changeset.claims.get(field_name="description")
        claim_citations = list(created_claim.citation_instances.all())
        assert len(claim_citations) == 1
        assert claim_citations[0].claim_id == created_claim.pk
        assert claim_citations[0].citation_source_id == citation_source.pk
        assert claim_citations[0].locator == "p. 2"

    def test_invalid_citation_rolls_back_changeset_and_claims(
        self, client, user, title
    ):
        client.force_login(user)

        resp = _patch(
            client,
            title.slug,
            {
                "fields": {"description": "Updated"},
                "citation": {"citation_instance_id": 999999},
            },
        )

        assert resp.status_code == 422
        # The title fixture's seed name claim is an ingest changeset; the rolled-
        # back edit must leave no user changeset behind.
        assert ChangeSet.objects.filter(user=user).count() == 0
        assert not Claim.objects.filter(
            user=user, field_name="description", value="Updated"
        ).exists()
