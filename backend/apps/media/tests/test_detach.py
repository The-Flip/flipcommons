"""Tests for media detach (removal) endpoint."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client

from apps.catalog.claims import build_media_attachment_claim
from apps.catalog.resolve import resolve_media_attachments
from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import EntityMedia, MediaAsset, MediaRendition
from apps.media.storage import build_storage_key
from apps.provenance.models import Claim
from apps.provenance.test_factories import user_changeset

User = get_user_model()

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def machine_model(db):
    return make_machine_model(name="Test Machine", slug="test-machine")


@pytest.fixture
def asset(db, user):
    return MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        original_filename="backglass.jpg",
        mime_type="image/jpeg",
        byte_size=1024,
        width=800,
        height=600,
        uploaded_by=user,
    )


@pytest.fixture
def renditions(db, asset):
    return [
        MediaRendition.objects.create(
            asset=asset,
            rendition_type=rendition_type,
            mime_type="image/webp" if rendition_type != "original" else "image/jpeg",
            byte_size=512,
            width=800,
            height=600,
        )
        for rendition_type in ("original", "thumb", "display")
    ]


def _attach_via_claims(entity, asset, user, category="backglass", is_primary=True):
    """Create a media attachment through the claims system."""
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
def attached(machine_model, asset, user):
    """Attach asset to machine_model via claims and resolve."""
    _attach_via_claims(machine_model, asset, user)


@pytest.fixture
def auth_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def anon_client():
    return Client()


# ---------------------------------------------------------------------------
# Detach endpoint
# ---------------------------------------------------------------------------


class TestDetachEndpoint:
    def test_successful_detach(
        self, auth_client, machine_model, asset, renditions, attached
    ):
        """Detaching removes the asset and all related rows."""
        assert EntityMedia.objects.filter(asset=asset).exists()
        assert MediaAsset.objects.filter(pk=asset.pk).exists()
        assert MediaRendition.objects.filter(asset=asset).count() == len(renditions)

        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        assert not EntityMedia.objects.filter(asset=asset).exists()
        assert not MediaAsset.objects.filter(pk=asset.pk).exists()
        assert not MediaRendition.objects.filter(asset_id=asset.pk).exists()

    def test_detach_tombstone_is_identity_only(
        self, auth_client, machine_model, asset, renditions, attached
    ):
        """The detach tombstone carries identity (media_asset) + exists only.

        Step 8 regression: build_media_attachment_claim drops the inert
        category/is_primary on exists=False, so the stored tombstone bytes are
        canonical. Asserted here because the endpoint deletes the asset but
        leaves the exists=false claim active.
        """
        claim_key, _ = build_media_attachment_claim(
            machine_model, asset.pk, exists=False
        )
        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 204

        tombstone = Claim.objects.get(claim_key=claim_key, is_active=True)
        assert tombstone.value == {"media_asset": asset.pk, "exists": False}

    def test_detach_deletes_storage_files(
        self,
        auth_client,
        machine_model,
        asset,
        renditions,
        attached,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        deleted_keys = []

        def fake_delete_from_storage(storage_keys):
            deleted_keys.append(sorted(storage_keys))

        monkeypatch.setattr(
            "apps.media.api.delete_from_storage", fake_delete_from_storage
        )

        with django_capture_on_commit_callbacks(execute=True):
            resp = auth_client.post(
                "/api/media/detach/",
                data={
                    "entity_type": "model",
                    "public_id": machine_model.public_id,
                    "asset_uuid": str(asset.uuid),
                },
                content_type="application/json",
            )

        assert resp.status_code == 204
        assert deleted_keys == [
            sorted(
                build_storage_key(asset.uuid, rendition_type)
                for rendition_type, _label in MediaRendition.RenditionType.choices
            )
        ]

    def test_detach_storage_failure_does_not_rollback_db(
        self,
        auth_client,
        machine_model,
        asset,
        renditions,
        attached,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        delete_attempts = []

        def raise_storage_failure(storage_keys):
            delete_attempts.append(sorted(storage_keys))
            raise RuntimeError("storage delete failed")

        monkeypatch.setattr(
            "apps.media.api.delete_from_storage",
            raise_storage_failure,
        )

        with django_capture_on_commit_callbacks(execute=True):
            resp = auth_client.post(
                "/api/media/detach/",
                data={
                    "entity_type": "model",
                    "public_id": machine_model.public_id,
                    "asset_uuid": str(asset.uuid),
                },
                content_type="application/json",
            )

        assert resp.status_code == 204
        assert delete_attempts == [
            sorted(
                build_storage_key(asset.uuid, rendition_type)
                for rendition_type, _label in MediaRendition.RenditionType.choices
            )
        ]
        assert not EntityMedia.objects.filter(asset=asset).exists()
        assert not MediaAsset.objects.filter(pk=asset.pk).exists()
        assert not MediaRendition.objects.filter(asset_id=asset.pk).exists()

    def test_detach_deletes_all_known_storage_keys_even_if_rows_are_missing(
        self,
        auth_client,
        machine_model,
        asset,
        attached,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        MediaRendition.objects.create(
            asset=asset,
            rendition_type="original",
            mime_type="image/jpeg",
            byte_size=512,
            width=800,
            height=600,
        )

        deleted_keys = []

        def fake_delete_from_storage(storage_keys):
            deleted_keys.append(sorted(storage_keys))

        monkeypatch.setattr(
            "apps.media.api.delete_from_storage", fake_delete_from_storage
        )

        with django_capture_on_commit_callbacks(execute=True):
            resp = auth_client.post(
                "/api/media/detach/",
                data={
                    "entity_type": "model",
                    "public_id": machine_model.public_id,
                    "asset_uuid": str(asset.uuid),
                },
                content_type="application/json",
            )

        assert resp.status_code == 204
        assert deleted_keys == [
            sorted(
                build_storage_key(asset.uuid, rendition_type)
                for rendition_type, _label in MediaRendition.RenditionType.choices
            )
        ]

    def test_detach_idempotent(
        self, auth_client, machine_model, asset, renditions, attached
    ):
        """Second detach of same asset returns 404 (already detached)."""
        auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_asset_not_attached_to_entity(self, auth_client, machine_model, asset):
        """Detaching an asset that exists but isn't attached to this entity fails."""
        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_auth_required(self, anon_client, machine_model, asset, attached):
        """Anonymous users cannot detach."""
        resp = anon_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code in (401, 403)
        assert EntityMedia.objects.filter(asset=asset).exists()

    def test_unknown_entity_type(self, auth_client, asset):
        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "nonexistent-type",
                "public_id": "whatever",
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_unknown_slug(self, auth_client, asset):
        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": "no-such-machine",
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 400

    def test_unknown_asset_uuid(self, auth_client, machine_model):
        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": "00000000-0000-0000-0000-000000000000",
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_malformed_asset_uuid(self, auth_client, machine_model):
        resp = auth_client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": "not-a-uuid",
            },
            content_type="application/json",
        )

        assert resp.status_code == 404
