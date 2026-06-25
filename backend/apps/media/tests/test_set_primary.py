"""Tests for media set-primary endpoint."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client

from apps.catalog.claims import build_media_attachment_claim
from apps.catalog.resolve import resolve_media_attachments
from apps.catalog.tests.conftest import make_machine_model
from apps.media.helpers import displayed_primary_asset_ids
from apps.media.models import EntityMedia, MediaAsset
from apps.provenance.models import Claim
from apps.provenance.test_factories import make_claim, user_changeset

User = get_user_model()

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """Create a media attachment through the claims system (not directly)."""
    from django.contrib.contenttypes.models import ContentType

    claim_key, claim_value = build_media_attachment_claim(
        entity, asset.pk, category=category, is_primary=is_primary
    )
    make_claim(
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


# ---------------------------------------------------------------------------
# Set-primary endpoint
# ---------------------------------------------------------------------------


class TestSetPrimaryEndpoint:
    def test_set_primary(self, auth_client, machine_model, user):
        """Setting primary on a non-primary asset makes it primary."""
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=False
        )

        resp = auth_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        em = EntityMedia.objects.get(asset=asset)
        assert em.is_primary is True

    def test_demotes_previous_primary(self, auth_client, machine_model, user):
        """Setting primary on asset B demotes asset A in same category."""
        asset_a = _make_asset(user, "a.jpg")
        asset_b = _make_asset(user, "b.jpg")
        _attach_via_claims(
            machine_model, asset_a, user, category="backglass", is_primary=True
        )
        _attach_via_claims(
            machine_model, asset_b, user, category="backglass", is_primary=False
        )

        resp = auth_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset_b.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        assert EntityMedia.objects.get(asset=asset_b).is_primary is True
        assert EntityMedia.objects.get(asset=asset_a).is_primary is False

        # The promote and demote are modeled as two claims in one ChangeSet.
        ct = ContentType.objects.get_for_model(type(machine_model))
        claim_a = Claim.objects.filter(
            content_type=ct,
            object_id=machine_model.pk,
            claim_key=f"media_attachment|media_asset:{asset_a.pk}",
        ).latest("created_at")
        claim_b = Claim.objects.filter(
            content_type=ct,
            object_id=machine_model.pk,
            claim_key=f"media_attachment|media_asset:{asset_b.pk}",
        ).latest("created_at")
        assert claim_a.value["is_primary"] is False
        assert claim_b.value["is_primary"] is True
        assert claim_a.changeset_id == claim_b.changeset_id

    def test_set_primary_on_older_asset_takes_effect(
        self, auth_client, machine_model, user
    ):
        """Regression guard: promoting an *older* asset over a newer primary
        actually moves the displayed primary (the read-time tiebreak alone,
        without the demotion claim, would keep the wrong one)."""
        asset_old = _make_asset(user, "old.jpg")
        asset_new = _make_asset(user, "new.jpg")
        _attach_via_claims(
            machine_model, asset_old, user, category="backglass", is_primary=False
        )
        _attach_via_claims(
            machine_model, asset_new, user, category="backglass", is_primary=True
        )

        resp = auth_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset_old.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        assert displayed_primary_asset_ids(
            EntityMedia.objects.filter(content_type__model="machinemodel")
        ) == {asset_old.pk}

    def test_different_category_unaffected(self, auth_client, machine_model, user):
        """Setting primary in one category doesn't affect another."""
        backglass = _make_asset(user, "bg.jpg")
        playfield = _make_asset(user, "pf.jpg")
        _attach_via_claims(
            machine_model, backglass, user, category="backglass", is_primary=True
        )
        _attach_via_claims(
            machine_model, playfield, user, category="playfield", is_primary=True
        )

        new_bg = _make_asset(user, "bg2.jpg")
        _attach_via_claims(
            machine_model, new_bg, user, category="backglass", is_primary=False
        )

        resp = auth_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(new_bg.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        # Playfield primary unchanged
        assert EntityMedia.objects.get(asset=playfield).is_primary is True

    def test_already_primary_is_noop(self, auth_client, machine_model, user):
        """Setting primary on an already-primary asset succeeds without error."""
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=True
        )

        resp = auth_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 204
        assert EntityMedia.objects.get(asset=asset).is_primary is True

    def test_auth_required(self, anon_client, machine_model, user):
        asset = _make_asset(user)
        _attach_via_claims(
            machine_model, asset, user, category="backglass", is_primary=False
        )

        resp = anon_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code in (401, 403)
        # Rejected, so no promote claim was written: the row keeps its raw
        # is_primary=False (the lone attachment is the displayed primary only
        # via read-time auto-promotion).
        assert EntityMedia.objects.get(asset=asset).is_primary is False

    def test_asset_not_attached(self, auth_client, machine_model, user):
        """Cannot set primary on an asset not attached to this entity."""
        asset = _make_asset(user)

        resp = auth_client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_unknown_asset_uuid(self, auth_client, machine_model):
        resp = auth_client.post(
            "/api/media/set-primary/",
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
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": "not-a-uuid",
            },
            content_type="application/json",
        )

        assert resp.status_code == 404
