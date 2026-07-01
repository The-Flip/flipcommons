"""Tests for cited edit evidence endpoint."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Title
from apps.citation.test_factories import make_citation_link, make_citation_source
from apps.claim_edit.claim_write import ClaimSpec, execute_claims
from apps.provenance.models import ClaimCitationInstance
from apps.provenance.schemas import CitationReferenceInputSchema
from apps.provenance.test_factories import (
    cite_claim,
    make_citation_instance,
    make_claim,
    user_changeset,
)

User = get_user_model()


@pytest.fixture
def title(db, bootstrap_source):
    title = Title.objects.create(name="Medieval Madness", slug="medieval-madness")
    make_claim(title, "name", "Medieval Madness", ingest_source=bootstrap_source)
    return title


@pytest.fixture
def citation_source(db):
    source = make_citation_source(name="Williams Flyer", source_type="web")
    make_citation_link(
        citation_source=source,
        link_type="homepage",
        url="https://example.com/flyer",
        label="Scan",
    )
    return source


@pytest.mark.django_db
class TestCitedEditEvidence:
    def test_returns_cited_changesets_with_fields_and_citation_details(
        self, client, user, title, citation_source
    ):
        changeset = user_changeset(user, note="Documented the flyer")
        year_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        desc_claim = make_claim(
            title, "description", "Updated copy", user=user, changeset=changeset
        )
        cite_claim(year_claim, citation_source=citation_source, locator="p. 2")
        cite_claim(desc_claim, citation_source=citation_source, locator="p. 2")

        resp = client.get("/api/pages/sources/title/medieval-madness/")

        assert resp.status_code == 200
        evidence = resp.json()["evidence"]
        assert len(evidence) == 1
        assert evidence[0]["note"] == "Documented the flyer"
        assert set(evidence[0]["fields"]) == {"description", "name"}
        assert len(evidence[0]["citations"]) == 1
        assert evidence[0]["citations"][0]["source_name"] == "Williams Flyer"
        assert evidence[0]["citations"][0]["locator"] == "p. 2"
        assert evidence[0]["citations"][0]["links"] == [
            {"url": "https://example.com/flyer", "label": "Scan"}
        ]

    def test_coalesces_repeated_copied_claim_citations(
        self, client, user, title, citation_source
    ):
        changeset = user_changeset(user, note="Grouped edit")
        first_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        second_claim = make_claim(
            title, "description", "Updated copy", user=user, changeset=changeset
        )
        cite_claim(first_claim, citation_source=citation_source, locator="p. 3")
        cite_claim(second_claim, citation_source=citation_source, locator="p. 3")

        resp = client.get("/api/pages/sources/title/medieval-madness/")

        assert resp.status_code == 200
        assert len(resp.json()["evidence"][0]["citations"]) == 1

    def test_omits_uncited_changesets(self, client, user, title, citation_source):
        uncited = user_changeset(user, note="Uncited cleanup")
        cited = user_changeset(user, note="Cited update")
        make_claim(title, "description", "Cleanup", user=user, changeset=uncited)
        cited_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=cited
        )
        cite_claim(cited_claim, citation_source=citation_source)

        resp = client.get("/api/pages/sources/title/medieval-madness/")

        assert resp.status_code == 200
        assert [item["note"] for item in resp.json()["evidence"]] == ["Cited update"]

    def test_soft_deleted_entity_still_returns_sources(
        self, client, user, title, citation_source
    ):
        """Soft-delete is soft: sources page remains inspectable by public_id.

        Policy: provenance surfaces intentionally use the default manager
        (not ``.active()``) so deleted entities keep their claims and
        citations visible to direct API callers. See ``sources_page``
        docstring.
        """
        changeset = user_changeset(user, note="Documented the flyer")
        cited_claim = make_claim(
            title, "name", "Medieval Madness (1997)", user=user, changeset=changeset
        )
        cite_claim(cited_claim, citation_source=citation_source)

        title.status = "deleted"
        title.save(update_fields=["status"])

        resp = client.get("/api/pages/sources/title/medieval-madness/")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sources"]) >= 1
        assert len(body["evidence"]) == 1
        assert body["evidence"][0]["note"] == "Documented the flyer"


@pytest.mark.django_db
class TestScalarCitationJoin:
    def test_execute_claims_fans_a_join_row_to_every_claim(
        self, user, title, citation_source
    ):
        # The engine's scalar-cite path records a ClaimCitationInstance support
        # edge for each per-claim instance it mints. The input schema references
        # a pre-existing *template* instance by id; the join rows must land on the
        # per-claim instances the engine mints, not on the template.
        template = make_citation_instance(
            citation_source=citation_source, locator="p. 9"
        )
        execute_claims(
            title,
            [
                ClaimSpec(field_name="name", value="Medieval Madness (1997)"),
                ClaimSpec(field_name="description", value="Updated copy"),
            ],
            user=user,
            citation=CitationReferenceInputSchema(citation_instance_id=template.pk),
        )

        links = ClaimCitationInstance.objects.select_related(
            "citation_instance", "claim"
        )
        assert links.count() == 2
        fields = set()
        for link in links:
            instance = link.citation_instance
            assert instance.pk != template.pk  # a per-claim instance, not template
            assert instance.citation_source_id == citation_source.pk
            # The join and the FK point at the same per-claim instance.
            assert instance.claim_id == link.claim_id
            fields.add(link.claim.field_name)
        assert fields == {"name", "description"}
