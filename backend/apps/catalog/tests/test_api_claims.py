"""Tests for PATCH /api/models/{public_id}/claims/ endpoint."""

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.resolve import resolve_model
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim, user_changeset

User = get_user_model()


@pytest.fixture
def low_priority_source(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def pm(db, bootstrap_source):
    pm = make_machine_model(name="Medieval Madness", slug="medieval-madness", year=1997)
    make_claim(pm, "name", "Medieval Madness", source=bootstrap_source)
    return pm


@pytest.mark.django_db
class TestPatchClaimsAuth:
    def test_anonymous_gets_401(self, client, pm):
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        assert resp.status_code in (401, 403)

    def test_authenticated_user_can_patch(self, client, user, pm):
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        assert resp.status_code == 200


@pytest.mark.django_db
class TestPatchClaimsValidation:
    def test_unknown_field_returns_422(self, client, user, pm):
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"nonexistent_field": "value"}}',
            content_type="application/json",
        )
        assert resp.status_code == 422

    def test_nonexistent_slug_returns_404(self, client, user):
        client.force_login(user)
        resp = client.patch(
            "/api/models/does-not-exist/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_clearing_required_title_returns_422(self, client, user, pm):
        """title is NOT NULL on MachineModel — clearing it must be rejected."""
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"title": null}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "title" in body["detail"]["field_errors"]

    def test_malformed_nested_body_uses_structured_422_envelope(self, client, user, pm):
        """Pydantic's malformed-body 422 reshapes to ``{detail: {message,
        field_errors, form_errors}}`` via the global ``ValidationError``
        handler, with field keys derived from ``loc[-1]``."""
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"gameplay_features": [{"slug": "tilt", "count": "not-an-int"}]}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        body = resp.json()
        detail = body["detail"]
        assert set(detail.keys()) == {"kind", "message", "field_errors", "form_errors"}
        assert detail["kind"] == "validation_error"
        # ``loc`` is ("body", "gameplay_features", 0, "count") — leaf wins.
        assert "count" in detail["field_errors"]
        assert "gameplay_features" not in detail["field_errors"]


@pytest.mark.django_db
class TestPatchClaimsPersistence:
    def test_claim_created_for_user(self, client, user, pm):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 1998}}',
            content_type="application/json",
        )
        claim = pm.claims.get(actor=user.actor, field_name="year", is_active=True)
        assert claim.value == 1998
        assert claim.actor.backing_model == "user"

    def test_repeated_edit_supersedes_previous_claim(self, client, user, pm):
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
        active = pm.claims.filter(actor=user.actor, field_name="year", is_active=True)
        inactive = pm.claims.filter(
            actor=user.actor, field_name="year", is_active=False
        )
        assert active.count() == 1
        assert inactive.count() == 1
        assert active.first().value == 1999

    def test_model_is_resolved_after_patch(self, client, user, pm):
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 2001, "name": "Updated Name"}}',
            content_type="application/json",
        )
        data = resp.json()
        assert data["year"] == 2001
        assert data["name"] == "Updated Name"

        pm.refresh_from_db()
        assert pm.year == 2001
        assert pm.name == "Updated Name"

    def test_slug_can_be_changed(self, client, user, pm):
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"slug": "medieval-madness-remastered"}}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "medieval-madness-remastered"

        pm.refresh_from_db()
        assert pm.slug == "medieval-madness-remastered"
        assert client.get(f"/api/pages/model/{pm.slug}").status_code == 200
        assert client.get("/api/pages/model/medieval-madness").status_code == 404

    def test_duplicate_slug_returns_422(self, client, user, pm):
        make_machine_model(name="Other Game", slug="other-game")
        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"slug": "other-game"}}',
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert "unique" in resp.json()["detail"]["message"].lower()

    def test_user_claim_beats_lower_priority_source(
        self, client, user, pm, low_priority_source
    ):
        make_claim(pm, "name", "Medieval Madness", source=low_priority_source)
        make_claim(pm, "year", 1997, source=low_priority_source)
        resolve_model(pm)
        pm.refresh_from_db()
        assert pm.year == 1997

        client.force_login(user)
        resp = client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"year": 2000}}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["year"] == 2000

        pm.refresh_from_db()
        assert pm.year == 2000


@pytest.mark.django_db
class TestUserClaimResolution:
    """Resolution logic correctly handles user-attributed claims."""

    def test_user_claim_wins_over_lower_priority_source(
        self, user, pm, low_priority_source
    ):
        make_claim(pm, "name", "Medieval Madness", source=low_priority_source)
        make_claim(pm, "year", 1990, source=low_priority_source)
        make_claim(
            pm, "year", 2000, user=user, changeset=user_changeset(user)
        )  # priority 10000 > 10

        resolved = resolve_model(pm)
        assert resolved.year == 2000

    def test_source_wins_over_lower_priority_user(self, user, pm):
        high_source = Source.objects.create(
            name="HighPri", source_type="editorial", priority=50000
        )
        make_claim(pm, "name", "Medieval Madness", source=high_source)
        make_claim(pm, "year", 1990, source=high_source)
        make_claim(
            pm, "year", 2000, user=user, changeset=user_changeset(user)
        )  # priority 10000 < 50000

        resolved = resolve_model(pm)
        assert resolved.year == 1990
