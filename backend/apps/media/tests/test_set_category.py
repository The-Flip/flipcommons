"""Tests for media set-category endpoint."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client

from apps.catalog.claims import build_media_attachment_claim
from apps.catalog.resolve import resolve_media_attachments
from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import EntityMedia, MediaAsset
from apps.provenance.models import Claim
from apps.provenance.test_factories import user_changeset

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def machine_model(db):
    return make_machine_model(name="Test Machine", slug="test-machine")


def _make_asset(user, filename="photo.jpg"):
    return MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        original_filename=filename,
        mime_type="image/jpeg",
        byte_size=1024,
        width=800,
        height=600,
        uploaded_by=user,
    )


def _attach_via_claims(entity, asset, user, category="backglass", is_primary=False):
    claim_key, claim_value = build_media_attachment_claim(
        entity, asset.pk, category=category, is_primary=is_primary
    )
    Claim.objects.assert_claim(
        entity,
        "media_attachment",
        claim_value,
        user=user,
        claim_key=claim_key,
        changeset=user_changeset(user),
    )
    ct = ContentType.objects.get_for_model(type(entity))
    resolve_media_attachments(content_type_id=ct.id, subject_ids={entity.pk})


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def anon_client():
    return Client()


class TestSetCategoryEndpoint:
    def test_change_category(self, auth_client, machine_model, user):
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=True
        )

        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        em = EntityMedia.objects.get(asset=asset)
        assert em.category == "playfield"

    def test_lone_attachment_auto_promotes_after_move(
        self, auth_client, machine_model, user
    ):
        """A moved attachment that is alone in its new category auto-promotes."""
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=True
        )

        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        em = EntityMedia.objects.get(asset=asset)
        assert em.is_primary is True

    def test_does_not_demote_existing_primary_in_new_category(
        self, auth_client, machine_model, user
    ):
        """Recategorizing a primary asset must not demote the new category's primary."""
        moved = _make_asset(user, "moved.jpg")
        existing_primary = _make_asset(user, "existing.jpg")
        _attach_via_claims(
            machine_model, moved, user, category="backglass", is_primary=True
        )
        _attach_via_claims(
            machine_model,
            existing_primary,
            user,
            category="playfield",
            is_primary=True,
        )

        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(moved.uuid),
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        assert EntityMedia.objects.get(asset=existing_primary).is_primary is True
        assert EntityMedia.objects.get(asset=moved).is_primary is False

    def test_same_category_is_noop(self, auth_client, machine_model, user):
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=True
        )

        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "backglass",
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        assert EntityMedia.objects.get(asset=asset).category == "backglass"

    def test_invalid_category(self, auth_client, machine_model, user):
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=True
        )

        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "not-a-real-category",
            },
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert EntityMedia.objects.get(asset=asset).category == "backglass"

    def test_auth_required(self, anon_client, machine_model, user):
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=True
        )

        resp = anon_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code in (401, 403)
        assert EntityMedia.objects.get(asset=asset).category == "backglass"

    def test_asset_not_attached(self, auth_client, machine_model, user):
        asset = _make_asset(user)

        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_unknown_asset_uuid(self, auth_client, machine_model):
        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": "00000000-0000-0000-0000-000000000000",
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_malformed_asset_uuid(self, auth_client, machine_model):
        resp = auth_client.post(
            "/api/media/set-category/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": "not-a-uuid",
                "category": "playfield",
            },
            content_type="application/json",
        )

        assert resp.status_code == 404
