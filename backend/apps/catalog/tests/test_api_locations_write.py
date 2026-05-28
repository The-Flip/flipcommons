"""Tests for /api/locations/ write routes.

Covers:

* ``POST /api/locations/`` (top-level country create)
* ``POST /api/locations/{parent_public_id}/children/`` (child create)
* ``PATCH /api/locations/{public_id}/claims/``
* ``GET /api/locations/{public_id}/delete-preview/``
* ``POST /api/locations/{public_id}/delete/``
* ``POST /api/locations/{public_id}/restore/``

Plus unit tests for the path / type derivation helpers in
:mod:`apps.catalog.services.location_paths`.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.catalog.api.edit_claims import StructuredValidationError
from apps.catalog.models import (
    CorporateEntity,
    CorporateEntityLocation,
    Location,
    Manufacturer,
)
from apps.catalog.services.location_paths import (
    compute_location_path,
    derive_child_location_type,
    lookup_child_division,
)
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_location(location_path, name, location_type, parent=None, divisions=None):
    slug = location_path.rsplit("/", 1)[-1]
    return Location.objects.create(
        location_path=location_path,
        slug=slug,
        name=name,
        location_type=location_type,
        parent=parent,
        divisions=divisions,
    )


@pytest.fixture
def usa(db):
    return _make_location("usa", "USA", "country", divisions=["state", "city"])


@pytest.fixture
def il(db, usa):
    return _make_location("usa/il", "Illinois", "state", parent=usa)


@pytest.fixture
def chicago(db, il):
    return _make_location("usa/il/chicago", "Chicago", "city", parent=il)


@pytest.fixture
def netherlands(db):
    # No divisions declared → child create raises.
    return _make_location("netherlands", "Netherlands", "country")


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def _patch(client, path, body):
    return client.patch(path, data=json.dumps(body), content_type="application/json")


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestComputeLocationPath:
    def test_top_level_is_just_slug(self):
        assert compute_location_path(None, "usa") == "usa"

    def test_child_concatenates(self, usa):
        assert compute_location_path(usa, "il") == "usa/il"

    def test_grandchild_concatenates(self, il):
        assert compute_location_path(il, "chicago") == "usa/il/chicago"


class TestLookupChildDivision:
    def test_in_range(self):
        assert lookup_child_division(["state", "city"], 0) == "state"
        assert lookup_child_division(["state", "city"], 1) == "city"

    def test_exhausted(self):
        assert lookup_child_division(["state", "city"], 2) is None

    def test_missing(self):
        assert lookup_child_division(None, 0) is None
        assert lookup_child_division([], 0) is None


class TestDeriveChildLocationType:
    def test_usa_first_tier_is_state(self, usa):
        assert derive_child_location_type(usa) == "state"

    def test_usa_second_tier_is_city(self, il):
        assert derive_child_location_type(il) == "city"

    def test_france_three_tiers(self, db):
        france = _make_location(
            "france", "France", "country", divisions=["region", "department", "city"]
        )
        idf = _make_location("france/idf", "Île-de-France", "region", parent=france)
        paris_dept = _make_location("france/idf/75", "Paris", "department", parent=idf)
        assert derive_child_location_type(france) == "region"
        assert derive_child_location_type(idf) == "department"
        assert derive_child_location_type(paris_dept) == "city"

    def test_missing_divisions_raises(self, netherlands):
        with pytest.raises(StructuredValidationError) as exc:
            derive_child_location_type(netherlands)
        assert "no divisions declared" in exc.value.form_errors[0]

    def test_too_deep_raises(self, chicago):
        # USA declares 2 division levels; chicago is at depth 2,
        # so a level-3 child has no derivable type.
        with pytest.raises(StructuredValidationError) as exc:
            derive_child_location_type(chicago)
        assert "2 division level" in exc.value.form_errors[0]


# ---------------------------------------------------------------------------
# Top-level (country) create
# ---------------------------------------------------------------------------


class TestTopLevelCreate:
    def test_anonymous_rejected(self, client, db):
        resp = _post(
            client,
            "/api/locations/",
            {"name": "USA", "slug": "usa", "divisions": ["state"]},
        )
        assert resp.status_code in (401, 403)
        assert not Location.objects.filter(location_path="usa").exists()

    def test_creates_country_with_divisions(self, client, user, db):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/",
            {"name": "USA", "slug": "usa", "divisions": ["state", "city"]},
        )
        assert resp.status_code == 201, resp.content

        loc = Location.objects.get(location_path="usa")
        assert loc.location_type == "country"
        assert loc.divisions == ["state", "city"]
        assert loc.parent is None

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        claim_fields = {
            c.field_name: c.value for c in Claim.objects.filter(changeset=cs)
        }
        # ``location_path`` is derived (claims_exempt) — no claim for it.
        assert "location_path" not in claim_fields
        assert claim_fields["location_type"] == "country"
        assert claim_fields["divisions"] == ["state", "city"]
        assert "parent" not in claim_fields  # top-level has no parent

    def test_rejects_duplicate_country_slug(self, client, user, usa):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/",
            {"name": "United States", "slug": "usa", "divisions": ["state"]},
        )
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert "slug" in body["field_errors"]

    def test_rejects_duplicate_country_name_case_insensitively(self, client, user, db):
        _make_location("georgia-country", "Georgia", "country", divisions=["region"])
        # Force the slug to differ so the slug check passes — we want to
        # exercise the name-uniqueness pre-check, not slug uniqueness.
        # (The DB constraint catalog_location_unique_name_at_root uses
        # Lower("name") so case differs but still collides.)
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/",
            {"name": "georgia", "slug": "georgia", "divisions": ["region"]},
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_allows_country_name_matching_descendant(self, client, user, usa, il):
        """A country named 'Georgia' should be creatable even if a state
        named 'Georgia' already exists under USA — the root-tier scope
        filter restricts the pre-check to ``parent IS NULL``."""
        _make_location("usa/ga", "Georgia", "state", parent=usa)
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/",
            {"name": "Georgia", "slug": "georgia", "divisions": ["region"]},
        )
        assert resp.status_code == 201, resp.content

    def test_rejects_missing_divisions(self, client, user, db):
        client.force_login(user)
        resp = _post(client, "/api/locations/", {"name": "USA", "slug": "usa"})
        assert resp.status_code == 422

    def test_rejects_empty_divisions(self, client, user, db):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/",
            {"name": "USA", "slug": "usa", "divisions": []},
        )
        assert resp.status_code == 422

    def test_rejects_client_supplied_location_type(self, client, user, db):
        """Schema-level (``extra='forbid'``) rejection of a forged type."""
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/",
            {
                "name": "USA",
                "slug": "usa",
                "divisions": ["state"],
                "location_type": "city",  # forbidden
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Child create
# ---------------------------------------------------------------------------


class TestChildCreate:
    def test_creates_state_under_country(self, client, user, usa):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/usa/children/",
            {"name": "Illinois", "slug": "il"},
        )
        assert resp.status_code == 201, resp.content

        il = Location.objects.get(location_path="usa/il")
        assert il.location_type == "state"
        assert il.parent_id == usa.pk

        cs = ChangeSet.objects.get(user=user, action=ChangeSetAction.CREATE)
        claim_fields = {
            c.field_name: c.value for c in Claim.objects.filter(changeset=cs)
        }
        # FK claim value is the parent's location_path (not slug).
        assert claim_fields["parent"] == "usa"
        assert claim_fields["location_type"] == "state"

    def test_creates_city_under_state(self, client, user, il):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/usa/il/children/",
            {"name": "Chicago", "slug": "chicago"},
        )
        assert resp.status_code == 201, resp.content
        chi = Location.objects.get(location_path="usa/il/chicago")
        assert chi.location_type == "city"

    def test_rejects_sibling_slug_collision(self, client, user, il):
        _make_location("usa/il/chicago", "Chicago", "city", parent=il)
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/usa/il/children/",
            {"name": "Chicago Heights", "slug": "chicago"},
        )
        assert resp.status_code == 422
        assert "slug" in resp.json()["detail"]["field_errors"]

    def test_rejects_sibling_name_collision_case_insensitively(self, client, user, il):
        _make_location("usa/il/chicago", "Chicago", "city", parent=il)
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/usa/il/children/",
            {"name": "chicago", "slug": "chicago-2"},
        )
        assert resp.status_code == 422
        assert "name" in resp.json()["detail"]["field_errors"]

    def test_allows_same_name_under_different_parents(self, client, user, usa, il):
        # Create state "Springfield" under IL...
        _make_location("usa/il/springfield", "Springfield", "city", parent=il)
        # ...and another state with the same name under a sibling parent.
        mo = _make_location("usa/mo", "Missouri", "state", parent=usa)
        client.force_login(user)
        resp = _post(
            client,
            f"/api/locations/{mo.location_path}/children/",
            {"name": "Springfield", "slug": "springfield"},
        )
        assert resp.status_code == 201, resp.content

    def test_rejects_client_supplied_divisions(self, client, user, usa):
        """Schema-level rejection of ``divisions`` on child create."""
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/usa/children/",
            {"name": "Illinois", "slug": "il", "divisions": ["county"]},
        )
        assert resp.status_code == 422

    def test_country_without_divisions_blocks_child_create(
        self, client, user, netherlands
    ):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/netherlands/children/",
            {"name": "Reuver", "slug": "reuver"},
        )
        assert resp.status_code == 422
        assert "no divisions declared" in resp.json()["detail"]["form_errors"][0]

    def test_too_deep_blocks_child_create(self, client, user, chicago):
        client.force_login(user)
        resp = _post(
            client,
            "/api/locations/usa/il/chicago/children/",
            {"name": "Loop", "slug": "loop"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH claims
# ---------------------------------------------------------------------------


class TestPatchClaims:
    def test_anonymous_rejected(self, client, usa):
        resp = _patch(
            client, "/api/locations/usa/claims/", {"fields": {"name": "United States"}}
        )
        assert resp.status_code in (401, 403)

    def test_edits_name_and_description(self, client, user, usa):
        client.force_login(user)
        resp = _patch(
            client,
            "/api/locations/usa/claims/",
            {"fields": {"name": "United States", "description": "A country"}},
        )
        assert resp.status_code == 200, resp.content
        usa.refresh_from_db()
        assert usa.name == "United States"
        assert usa.description == "A country"

    def test_edits_aliases(self, client, user, usa):
        client.force_login(user)
        resp = _patch(
            client,
            "/api/locations/usa/claims/",
            {"aliases": ["United States", "America"]},
        )
        assert resp.status_code == 200, resp.content
        usa.refresh_from_db()
        assert {a.value for a in usa.aliases.all()} == {"United States", "America"}

    def test_country_can_edit_divisions(self, client, user, usa):
        client.force_login(user)
        resp = _patch(
            client,
            "/api/locations/usa/claims/",
            {"divisions": ["state", "county", "city"]},
        )
        assert resp.status_code == 200, resp.content
        usa.refresh_from_db()
        assert usa.divisions == ["state", "county", "city"]

    def test_non_country_rejects_divisions(self, client, user, il):
        client.force_login(user)
        resp = _patch(
            client, "/api/locations/usa/il/claims/", {"divisions": ["county"]}
        )
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert "divisions" in body["field_errors"]

    @pytest.mark.parametrize("field", ["parent", "slug", "location_type"])
    def test_rejects_immutable_fields(self, client, user, il, field):
        client.force_login(user)
        resp = _patch(
            client,
            "/api/locations/usa/il/claims/",
            {"fields": {field: "anything"}},
        )
        assert resp.status_code == 422
        assert field in resp.json()["detail"]["field_errors"]


# ---------------------------------------------------------------------------
# Delete / preview / restore
# ---------------------------------------------------------------------------


def _make_ce_at(name, slug, location, *, status="active"):
    mfr = Manufacturer.objects.create(
        name=f"{name} Mfr", slug=f"{slug}-mfr", status="active"
    )
    ce = CorporateEntity.objects.create(
        name=name, slug=slug, manufacturer=mfr, status=status
    )
    CorporateEntityLocation.objects.create(corporate_entity=ce, location=location)
    return ce


class TestDelete:
    def test_active_child_blocks_delete(self, client, user, usa, il):
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/delete/", {})
        assert resp.status_code == 422
        body = resp.json()
        assert body["active_children_count"] >= 1

        usa.refresh_from_db()
        assert usa.status != "deleted"

    def test_active_cel_blocks_delete(self, client, user, chicago):
        _make_ce_at("Williams", "williams", chicago)
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/il/chicago/delete/", {})
        assert resp.status_code == 422
        assert resp.json()["blocked_by"]
        chicago.refresh_from_db()
        assert chicago.status != "deleted"

    def test_deleted_cel_does_not_block(self, client, user, chicago):
        _make_ce_at("Williams", "williams", chicago, status="deleted")
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/il/chicago/delete/", {})
        assert resp.status_code == 200, resp.content
        chicago.refresh_from_db()
        assert chicago.status == "deleted"

    def test_unblocked_delete_is_row_only(self, client, user, chicago, il):
        """Deleting a leaf must not cascade to anything else."""
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/il/chicago/delete/", {})
        assert resp.status_code == 200, resp.content
        chicago.refresh_from_db()
        il.refresh_from_db()
        assert chicago.status == "deleted"
        assert il.status != "deleted"

        cs = ChangeSet.objects.get(pk=resp.json()["changeset_id"])
        assert cs.action == ChangeSetAction.DELETE
        # Delete writes a single status claim on chicago only.
        affected = list(Claim.objects.filter(changeset=cs))
        assert len(affected) == 1
        assert affected[0].field_name == "status"
        assert affected[0].value == "deleted"


class TestRestore:
    def test_reactivates_row(self, client, user, chicago):
        chicago.status = "deleted"
        chicago.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/il/chicago/restore/", {})
        assert resp.status_code == 200, resp.content
        chicago.refresh_from_db()
        assert chicago.status != "deleted"

    def test_restore_blocked_when_parent_deleted(self, client, user, chicago, il):
        chicago.status = "deleted"
        chicago.save(update_fields=["status"])
        il.status = "deleted"
        il.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/il/chicago/restore/", {})
        assert resp.status_code == 422
        chicago.refresh_from_db()
        assert chicago.status == "deleted"

    def test_country_restore_succeeds(self, client, user, usa):
        """Top-level countries have ``parent=None``. The shared restore
        factory must tolerate a null parent rather than dereferencing it."""
        usa.status = "deleted"
        usa.save(update_fields=["status"])
        client.force_login(user)
        resp = _post(client, "/api/locations/usa/restore/", {})
        assert resp.status_code == 200, resp.content
        usa.refresh_from_db()
        assert usa.status != "deleted"


class TestDeletePreview:
    def test_country_delete_preview_succeeds(self, client, user, usa, il):
        """Top-level countries have ``parent=None``. The shared
        delete-preview factory must tolerate a null parent."""
        client.force_login(user)
        resp = client.get("/api/locations/usa/delete-preview/")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["parent"] is None
        # Active child (IL) should still surface in the preview.
        assert body["active_children_count"] >= 1

    def test_child_delete_preview_includes_parent(self, client, user, chicago):
        client.force_login(user)
        resp = client.get("/api/locations/usa/il/chicago/delete-preview/")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["parent"] is not None
        # A Location's public_id is its location_path, not its bare slug.
        assert body["parent"]["public_id"] == "usa/il"


# ---------------------------------------------------------------------------
# Edit-history / sources resolution by multi-segment public_id
# ---------------------------------------------------------------------------


class TestPageEndpointsByPath:
    def test_edit_history_resolves_multi_segment(self, client, user, chicago):
        client.force_login(user)
        # Generate at least one ChangeSet so the page has content.
        _patch(
            client,
            "/api/locations/usa/il/chicago/claims/",
            {"fields": {"name": "Chicago, IL"}},
        )
        resp = client.get("/api/pages/edit-history/location/usa/il/chicago/")
        assert resp.status_code == 200

    def test_sources_resolves_multi_segment(self, client, user, chicago):
        client.force_login(user)
        resp = client.get("/api/pages/sources/location/usa/il/chicago/")
        assert resp.status_code == 200
