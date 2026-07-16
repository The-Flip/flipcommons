"""Tests for GET /api/pages/edit-history/{entity_type}/{public_id}/ endpoint."""

from typing import Any

import pytest

from apps.accounts.test_factories import make_user
from apps.catalog.tests.conftest import make_machine_model
from apps.citation.test_factories import make_citation_link, make_citation_source
from apps.provenance.test_factories import (
    cite_claim,
    make_citation_instance,
    make_claim,
    make_ingest_source,
)


def _user_changesets(resp) -> list[dict[str, Any]]:
    """User-authored entries from an edit-history response.

    Seed/ingest claims now carry (ingest) ChangeSets — realistic, and visible in
    the full history just as ingested catalog data is in production. These tests
    are about *user* edit history, so they filter to it.
    """
    return [cs for cs in resp.json() if cs["attribution"]["author"]["kind"] == "user"]


@pytest.fixture
def source(db):
    return make_ingest_source(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def pm(db, bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    make_claim(pm, "name", "Medieval Madness", ingest_source=bootstrap_source)
    return pm


@pytest.mark.django_db
class TestEditHistoryEmpty:
    def test_no_changesets_returns_empty_list(self, client, pm):
        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        assert _user_changesets(resp) == []

    def test_nonexistent_slug_returns_404(self, client):
        resp = client.get("/api/pages/edit-history/model/does-not-exist/")
        assert resp.status_code == 404

    def test_source_claims_not_included(self, client, pm, source):
        """Source-attributed claims should not appear in *user* edit history."""
        make_claim(pm, "year", 1998, ingest_source=source)
        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        assert _user_changesets(resp) == []


@pytest.mark.django_db
class TestEditHistoryBasic:
    def test_single_changeset_returned(self, client, user, pm):
        """A single edit session shows up with field changes."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        data = _user_changesets(resp)
        assert len(data) == 1

        cs = data[0]
        assert cs["attribution"]["author"] == {
            "kind": "user",
            "username": user.username,
        }
        assert cs["note"] == ""
        assert len(cs["changes"]) == 1
        assert cs["changes"][0]["field_name"] == "year"
        assert cs["changes"][0]["new_value"]["raw"] == 1998
        # First edit — no old value
        assert cs["changes"][0]["old_value"] is None

    def test_old_value_shown_on_second_edit(self, client, user, pm):
        """When a field is edited twice, the second changeset shows old→new."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = _user_changesets(resp)
        assert len(data) == 2

        # Most recent first
        newest = data[0]
        assert newest["changes"][0]["field_name"] == "year"
        assert newest["changes"][0]["old_value"]["raw"] == 1998
        assert newest["changes"][0]["new_value"]["raw"] == 1999

        oldest = data[1]
        assert oldest["changes"][0]["old_value"] is None
        assert oldest["changes"][0]["new_value"]["raw"] == 1998


@pytest.mark.django_db
class TestEditHistoryFkDisplay:
    def test_fk_change_shows_entity_label_not_pk(self, client, user, pm):
        """An FK edit stores the target PK but history renders its label —
        via the same display shape relationship claims use — so the raw int
        never has to surface. The API still accepts the slug on the wire."""
        from apps.catalog.models import TechnologyGeneration

        ss = TechnologyGeneration.objects.create(name="Solid State", slug="solid-state")
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"technology_generation": "solid-state"}}',
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        change = _user_changesets(resp)[0]["changes"][0]
        assert change["field_name"] == "technology_generation"
        assert change["new_value"]["raw"] == ss.pk
        display = change["new_value"]["display"]
        assert display["kind"] == "relationship"
        assert display["identity"] == [
            {
                "key": "technology_generation",
                "label": "Solid State",
                "state": "resolved",
            }
        ]


@pytest.mark.django_db
class TestEditHistoryMultipleFields:
    def test_multi_field_changeset(self, client, user, pm):
        """A single edit that changes multiple fields shows all changes."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998, "player_count": 4}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = _user_changesets(resp)
        assert len(data) == 1

        field_names = {c["field_name"] for c in data[0]["changes"]}
        assert field_names == {"year", "player_count"}


@pytest.mark.django_db
class TestEditHistoryMultiUser:
    def test_old_value_uses_any_prior_claim(self, client, user, pm, db):
        """User B editing after User A should see User A's value as the old value."""
        user_b = make_user()

        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.force_login(user_b)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = _user_changesets(resp)
        assert len(data) == 2

        # User B's edit is newest — old value is User A's prior claim
        assert data[0]["attribution"]["author"] == {
            "kind": "user",
            "username": user_b.username,
        }
        assert data[0]["changes"][0]["old_value"]["raw"] == 1998
        assert data[0]["changes"][0]["new_value"]["raw"] == 1999

        # User A's edit — no prior claim, so no old value
        assert data[1]["attribution"]["author"] == {
            "kind": "user",
            "username": user.username,
        }
        assert data[1]["changes"][0]["old_value"] is None
        assert data[1]["changes"][0]["new_value"]["raw"] == 1998

    def test_old_value_uses_source_claim(self, client, user, pm, source):
        """A user edit shows the prior source/ingest claim's value as old."""
        make_claim(pm, "year", 1997, ingest_source=source)

        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1999}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = _user_changesets(resp)
        assert len(data) == 1
        assert data[0]["changes"][0]["old_value"]["raw"] == 1997
        assert data[0]["changes"][0]["new_value"]["raw"] == 1999

    def test_old_value_is_chronological_even_when_prior_claim_is_not_winner(
        self, client, user, pm
    ):
        """The ``old_value`` contract: the chronologically prior claim under
        the key, regardless of priority or winning state — history narrates
        the claim log, not resolution deltas. The two sources are
        priority-inverted so the chronological prior (newer, low priority)
        and the resolution winner (older, high priority) differ; a
        resolution-based ``old_value`` would show 2001 here."""
        high = make_ingest_source(
            name="Editorial", source_type="editorial", priority=100
        )
        low = make_ingest_source(name="Databases", source_type="database", priority=10)
        make_claim(pm, "year", 2001, ingest_source=high)
        make_claim(pm, "year", 1999, ingest_source=low)

        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1995}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = _user_changesets(resp)
        assert len(data) == 1
        assert data[0]["changes"][0]["old_value"]["raw"] == 1999
        assert data[0]["changes"][0]["new_value"]["raw"] == 1995


@pytest.mark.django_db
class TestEditHistoryOrdering:
    def test_newest_first(self, client, user, pm):
        """Changesets are returned newest first."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"player_count": 4}}',
            content_type="application/json",
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        data = _user_changesets(resp)
        assert len(data) == 2
        # Newest changeset (player_count) first
        assert data[0]["changes"][0]["field_name"] == "player_count"
        assert data[1]["changes"][0]["field_name"] == "year"


@pytest.mark.django_db
class TestEditHistorySoftDeleted:
    def test_soft_deleted_entity_still_returns_history(self, client, user, pm):
        """Soft-delete is soft: audit trail remains inspectable by public_id.

        Policy: provenance surfaces intentionally use the default manager
        (not ``.active()``) so deleted entities keep their history visible
        to direct API callers. See ``edit_history_page`` docstring.
        """
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        pm.status = "deleted"
        pm.save(update_fields=["status"])

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        data = _user_changesets(resp)
        assert len(data) == 1
        assert data[0]["changes"][0]["new_value"]["raw"] == 1998


@pytest.mark.django_db
class TestEditHistoryCitations:
    def test_attached_citation_carries_rich_metadata(self, client, user, pm):
        """Join-attached (supporting-evidence) citations expose the full
        source metadata, not just a name and one URL."""
        claim = make_claim(pm, "year", 1998, user=user)
        src = make_citation_source(
            name="The Toy Book",
            source_type="web",
            author="Ryan Vincent",
            year=2024,
        )
        make_citation_link(
            citation_source=src,
            url="https://toybook.com/wonderland/",
            link_type="reference",
        )
        cite_claim(claim, citation_source=src, locator="para. 2")

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        [cit] = _user_changesets(resp)[0]["changes"][0]["citations"]
        assert cit["source_name"] == "The Toy Book"
        assert cit["source_type"] == "web"
        assert cit["author"] == "Ryan Vincent"
        assert cit["year"] == 2024
        assert cit["locator"] == "para. 2"
        # Attached evidence has no inline marker, so no slug.
        assert cit["slug"] is None
        assert [link["url"] for link in cit["links"]] == [
            "https://toybook.com/wonderland/"
        ]

    def test_multiple_attached_citations_all_returned(self, client, user, pm):
        """A claim backed by several join-attached citations surfaces every
        one on the change, not just the first."""
        claim = make_claim(pm, "year", 1998, user=user)
        book = make_citation_source(name="The Encyclopedia of Pinball")
        web = make_citation_source(name="The Toy Book", source_type="web")
        cite_claim(claim, citation_source=book, locator="p. 42")
        cite_claim(claim, citation_source=web)

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        citations = _user_changesets(resp)[0]["changes"][0]["citations"]
        assert {(c["source_name"], c["locator"]) for c in citations} == {
            ("The Encyclopedia of Pinball", "p. 42"),
            ("The Toy Book", ""),
        }
        # Attached evidence has no inline markers.
        assert all(c["slug"] is None for c in citations)

    def test_inline_citations_returned_in_document_order(self, client, user, pm):
        """Inline ``[[cite:id:N]]`` markers in a markdown claim surface as
        citations on the change, slug-keyed and ordered by first appearance."""
        src_a = make_citation_source(
            name="The Toy Book", author="Ryan Vincent", year=2024
        )
        make_citation_link(
            citation_source=src_a,
            url="https://toybook.com/wonderland/",
            link_type="reference",
        )
        src_b = make_citation_source(name="Kickstarter")
        inst_a = make_citation_instance(citation_source=src_a)
        inst_b = make_citation_instance(citation_source=src_b)
        make_claim(
            pm,
            "description",
            f"Founded by veterans.[[cite:id:{inst_b.pk}]] "
            f"Debuted at Expo.[[cite:id:{inst_a.pk}]]",
            user=user,
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        citations = _user_changesets(resp)[0]["changes"][0]["citations"]
        assert [c["slug"] for c in citations] == [inst_b.slug, inst_a.slug]
        assert [c["source_name"] for c in citations] == ["Kickstarter", "The Toy Book"]
        toy_book = citations[1]
        assert toy_book["author"] == "Ryan Vincent"
        assert toy_book["year"] == 2024
        assert [link["url"] for link in toy_book["links"]] == [
            "https://toybook.com/wonderland/"
        ]

    def test_old_value_only_citations_included(self, client, user, pm):
        """A citation that appears only in the prior text (removed by the
        edit) still gets metadata, so the diff can label its marker."""
        inst_old = make_citation_instance(
            citation_source=make_citation_source(name="Pinside forum")
        )
        inst_kept = make_citation_instance(
            citation_source=make_citation_source(name="Kickstarter")
        )
        make_claim(
            pm,
            "description",
            f"Old text.[[cite:id:{inst_old.pk}]] Kept.[[cite:id:{inst_kept.pk}]]",
            user=user,
        )
        make_claim(
            pm,
            "description",
            f"New text. Kept.[[cite:id:{inst_kept.pk}]]",
            user=user,
        )

        resp = client.get(f"/api/pages/edit-history/model/{pm.slug}/")
        assert resp.status_code == 200
        newest = _user_changesets(resp)[0]
        citations = newest["changes"][0]["citations"]
        # New-text citations first (document order), then old-only ones.
        assert [c["slug"] for c in citations] == [inst_kept.slug, inst_old.slug]


@pytest.mark.django_db
class TestEditHistoryEntityTypeGuard:
    def test_unknown_entity_type_returns_404(self, client):
        resp = client.get("/api/pages/edit-history/nonexistent/some-slug/")
        assert resp.status_code == 404

    def test_non_linkable_entity_type_returns_404(self, client):
        """Models that aren't LinkableModel subclasses (e.g. Location) should be rejected."""
        resp = client.get("/api/pages/edit-history/location/some-slug/")
        assert resp.status_code == 404
