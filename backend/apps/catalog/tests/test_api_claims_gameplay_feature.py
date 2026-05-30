"""Tests for PATCH /api/gameplay-features/{public_id}/claims/."""

import json

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import GameplayFeature
from apps.provenance.models import ChangeSet

User = get_user_model()


def _only_changeset() -> ChangeSet:
    cs = ChangeSet.objects.first()
    assert cs is not None
    return cs


@pytest.fixture
def feature(db):
    return GameplayFeature.objects.create(name="Multiball", slug="multiball")


def _patch(client, slug, body):
    return client.patch(
        f"/api/gameplay-features/{slug}/claims/",
        data=json.dumps(body),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchGameplayFeatureAuth:
    def test_anonymous_gets_401(self, client, feature):
        resp = _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code in (401, 403)

    def test_authenticated_user_can_patch(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchGameplayFeatureValidation:
    def test_empty_request_returns_422(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {})
        assert resp.status_code == 422

    def test_empty_fields_no_parents_returns_422(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"fields": {}})
        assert resp.status_code == 422

    def test_unknown_field_returns_422(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"fields": {"nonexistent_field": "bad"}})
        assert resp.status_code == 422

    def test_nonexistent_slug_returns_404(self, client, user):
        client.force_login(user)
        resp = _patch(client, "does-not-exist", {"fields": {"name": "X"}})
        assert resp.status_code == 404

    def test_duplicate_name_returns_422(self, client, user, feature):
        GameplayFeature.objects.create(name="Drop Targets", slug="drop-targets")
        client.force_login(user)
        resp = _patch(client, feature.slug, {"fields": {"name": "Drop Targets"}})
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()

    def test_invalid_markdown_link_returns_422(self, client, user, feature):
        client.force_login(user)
        resp = _patch(
            client,
            feature.slug,
            {"fields": {"description": "Links to [[system:nope]]."}},
        )
        assert resp.status_code == 422
        assert "nope" in resp.json()["detail"]["message"].lower()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchGameplayFeaturePersistence:
    def test_claim_created_for_user(self, client, user, feature):
        client.force_login(user)
        _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        claim = feature.claims.get(user=user, field_name="description", is_active=True)
        assert claim.value == "Updated"

    def test_model_resolved_and_returned(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        data = resp.json()
        assert data["description"]["text"] == "Updated"
        feature.refresh_from_db()
        assert feature.description == "Updated"

    def test_repeated_edit_supersedes_previous(self, client, user, feature):
        client.force_login(user)
        _patch(client, feature.slug, {"fields": {"description": "First"}})
        _patch(client, feature.slug, {"fields": {"description": "Second"}})
        active = feature.claims.filter(
            user=user, field_name="description", is_active=True
        )
        inactive = feature.claims.filter(
            user=user, field_name="description", is_active=False
        )
        assert active.count() == 1
        assert inactive.count() == 1
        assert active.first().value == "Second"


# ---------------------------------------------------------------------------
# ChangeSet
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchGameplayFeatureChangeSet:
    def test_changeset_created_with_claims(self, client, user, feature):
        client.force_login(user)
        _patch(
            client,
            feature.slug,
            {"fields": {"name": "Multiball Mania", "description": "Updated"}},
        )
        assert ChangeSet.objects.count() == 1
        cs = _only_changeset()
        assert cs.user == user
        assert cs.claims.count() == 2
        assert set(cs.claims.values_list("field_name", flat=True)) == {
            "name",
            "description",
        }

    def test_changeset_stores_note(self, client, user, feature):
        client.force_login(user)
        _patch(
            client,
            feature.slug,
            {
                "fields": {"description": "Updated"},
                "note": "Corrected from IPDB listing",
            },
        )
        cs = _only_changeset()
        assert cs.note == "Corrected from IPDB listing"

    def test_changeset_note_in_sources_response(self, client, user, feature):
        client.force_login(user)
        _patch(
            client,
            feature.slug,
            {
                "fields": {"description": "Updated"},
                "note": "My edit note",
            },
        )
        resp = client.get(f"/api/pages/sources/gameplay-feature/{feature.slug}/")
        desc_claim = next(
            c for c in resp.json()["sources"] if c["field_name"] == "description"
        )
        assert desc_claim["changeset_note"] == "My edit note"

    def test_changeset_note_defaults_to_empty(self, client, user, feature):
        client.force_login(user)
        _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        cs = _only_changeset()
        assert cs.note == ""


# ---------------------------------------------------------------------------
# Parents
# ---------------------------------------------------------------------------


@pytest.fixture
def parent_feature(db):
    return GameplayFeature.objects.create(name="Scoring", slug="scoring")


@pytest.fixture
def child_feature(db):
    return GameplayFeature.objects.create(name="Drop Targets", slug="drop-targets")


@pytest.mark.django_db
class TestPatchGameplayFeatureParents:
    def test_add_parents(self, client, user, feature, parent_feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"parents": ["scoring"]})
        assert resp.status_code == 200
        assert [p["public_id"] for p in resp.json()["parents"]] == ["scoring"]
        feature.refresh_from_db()
        assert list(feature.parents.values_list("slug", flat=True)) == ["scoring"]

    def test_remove_parents(self, client, user, feature, parent_feature):
        # Set up an existing parent via the API.
        client.force_login(user)
        _patch(client, feature.slug, {"parents": ["scoring"]})
        # Now remove all parents.
        resp = _patch(client, feature.slug, {"parents": []})
        assert resp.status_code == 200
        assert resp.json()["parents"] == []
        feature.refresh_from_db()
        assert feature.parents.count() == 0

    def test_replace_parents(
        self, client, user, feature, parent_feature, child_feature
    ):
        client.force_login(user)
        _patch(client, feature.slug, {"parents": ["scoring"]})
        resp = _patch(client, feature.slug, {"parents": ["drop-targets"]})
        assert resp.status_code == 200
        assert [p["public_id"] for p in resp.json()["parents"]] == ["drop-targets"]

    def test_invalid_parent_slug_returns_422(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"parents": ["nonexistent"]})
        assert resp.status_code == 422

    def test_self_link_returns_422(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"parents": ["multiball"]})
        assert resp.status_code == 422

    def test_cycle_returns_422(self, client, user, feature, parent_feature):
        # Make "scoring" a child of "multiball" first.
        client.force_login(user)
        _patch(client, parent_feature.slug, {"parents": ["multiball"]})
        # Now try to make "scoring" a parent of "multiball" — creates a cycle.
        resp = _patch(client, feature.slug, {"parents": ["scoring"]})
        assert resp.status_code == 422

    def test_noop_parents_returns_422(self, client, user, feature):
        """Submitting the same parents that already exist is a no-op → 422."""
        client.force_login(user)
        resp = _patch(client, feature.slug, {"parents": []})
        assert resp.status_code == 422
        assert ChangeSet.objects.count() == 0

    def test_parents_only_no_fields_succeeds(
        self, client, user, feature, parent_feature
    ):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"parents": ["scoring"]})
        assert resp.status_code == 200

    def test_combined_scalar_and_parents(self, client, user, feature, parent_feature):
        client.force_login(user)
        resp = _patch(
            client,
            feature.slug,
            {"fields": {"description": "Updated"}, "parents": ["scoring"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"]["text"] == "Updated"
        assert [p["public_id"] for p in data["parents"]] == ["scoring"]
        # All claims in one changeset.
        assert ChangeSet.objects.count() == 1
        cs = _only_changeset()
        assert cs.claims.count() == 2  # description + parent

    def test_null_parents_leaves_parents_unchanged(
        self, client, user, feature, parent_feature
    ):
        """When parents key is omitted (None), existing parents are not touched."""
        client.force_login(user)
        _patch(client, feature.slug, {"parents": ["scoring"]})
        # PATCH with only fields, no parents key.
        resp = _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code == 200
        assert [p["public_id"] for p in resp.json()["parents"]] == ["scoring"]


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchGameplayFeatureAliases:
    """Alias PATCH tests.

    Note: The GameplayFeature detail serializer filters aliases that
    normalize to the same string as the canonical name (e.g. "Multi-Ball"
    is hidden when the feature is "Multiball").  Tests that check the API
    response use aliases that are clearly distinct; tests that check DB
    state can use any alias.
    """

    def test_add_aliases(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"aliases": ["MB", "Super Shot"]})
        assert resp.status_code == 200
        assert sorted(resp.json()["aliases"]) == ["MB", "Super Shot"]
        feature.refresh_from_db()
        assert sorted(feature.aliases.values_list("value", flat=True)) == [
            "MB",
            "Super Shot",
        ]

    def test_remove_aliases(self, client, user, feature):
        client.force_login(user)
        _patch(client, feature.slug, {"aliases": ["MB"]})
        resp = _patch(client, feature.slug, {"aliases": []})
        assert resp.status_code == 200
        assert resp.json()["aliases"] == []
        assert feature.aliases.count() == 0

    def test_display_case_preserved(self, client, user, feature):
        """User-typed case should round-trip, not be lowercased."""
        client.force_login(user)
        resp = _patch(client, feature.slug, {"aliases": ["Super Shot"]})
        assert "Super Shot" in resp.json()["aliases"]
        feature.refresh_from_db()
        assert feature.aliases.get().value == "Super Shot"

    def test_display_case_update(self, client, user, feature):
        """Changing only the case of an existing alias should update it."""
        client.force_login(user)
        _patch(client, feature.slug, {"aliases": ["super shot"]})
        resp = _patch(client, feature.slug, {"aliases": ["Super Shot"]})
        assert resp.status_code == 200
        feature.refresh_from_db()
        assert feature.aliases.get().value == "Super Shot"

    def test_aliases_only_no_fields_succeeds(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"aliases": ["MB"]})
        assert resp.status_code == 200

    def test_null_aliases_leaves_aliases_unchanged(self, client, user, feature):
        """When aliases key is omitted (None), existing aliases are not touched."""
        client.force_login(user)
        _patch(client, feature.slug, {"aliases": ["MB"]})
        resp = _patch(client, feature.slug, {"fields": {"description": "Updated"}})
        assert resp.status_code == 200
        assert resp.json()["aliases"] == ["MB"]

    def test_duplicate_aliases_deduplicated(self, client, user, feature):
        client.force_login(user)
        resp = _patch(client, feature.slug, {"aliases": ["Super Shot", "super shot"]})
        assert resp.status_code == 200
        assert len(resp.json()["aliases"]) == 1

    def test_noop_aliases_returns_422(self, client, user, feature):
        """Submitting the same aliases that already exist is a no-op → 422."""
        client.force_login(user)
        resp = _patch(client, feature.slug, {"aliases": []})
        assert resp.status_code == 422
        assert ChangeSet.objects.count() == 0
