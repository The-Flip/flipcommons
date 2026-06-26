"""Tests for uploaded-first fallback in catalog API image URLs."""

from __future__ import annotations

import pytest
from constance.test import override_config
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from apps.catalog.api.images import extract_image_attribution, extract_image_urls
from apps.catalog.models import MachineModel
from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import EntityMedia, MediaAsset
from apps.media.storage import build_public_url, build_storage_key

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
def failed_asset(db, user):
    return MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.FAILED,
        original_filename="bad.jpg",
        mime_type="image/jpeg",
        byte_size=512,
        uploaded_by=user,
    )


@pytest.fixture
def ct_mm(db):
    return ContentType.objects.get_for_model(MachineModel)


def _attach(ct, entity, asset, category=None, is_primary=True):
    """Create an EntityMedia row directly (bypassing claims for unit tests)."""
    return EntityMedia.objects.create(
        content_type=ct,
        object_id=entity.pk,
        asset=asset,
        category=category,
        is_primary=is_primary,
    )


def _expected_thumb(asset):
    return build_public_url(build_storage_key(asset.uuid, "thumb"))


def _expected_hero(asset):
    return build_public_url(build_storage_key(asset.uuid, "display"))


OPDB_EXTRA_DATA = {
    "opdb.images": [
        {
            "primary": True,
            "urls": {
                "small": "https://img.opdb.org/s.jpg",
                "medium": "https://img.opdb.org/m.jpg",
                "large": "https://img.opdb.org/l.jpg",
            },
        }
    ],
    "opdb.images.__permissiveness_rank": 50,
    "opdb.images.__license_slug": "cc-by-sa-4-0",
}


# ---------------------------------------------------------------------------
# extract_image_urls — uploaded-first fallback
# ---------------------------------------------------------------------------


class TestUploadedFirstFallback:
    def test_uploaded_backglass_primary(self, machine_model, asset, ct_mm):
        em = _attach(ct_mm, machine_model, asset, category="backglass")
        primary_media = [em]

        thumb, hero = extract_image_urls({}, primary_media)

        assert thumb == _expected_thumb(asset)
        assert hero == _expected_hero(asset)

    def test_uploaded_non_backglass_fallback(self, machine_model, asset, ct_mm):
        """When no backglass exists, uses first available primary."""
        em = _attach(ct_mm, machine_model, asset, category="playfield")
        primary_media = [em]

        thumb, hero = extract_image_urls({}, primary_media)

        assert thumb == _expected_thumb(asset)
        assert hero == _expected_hero(asset)

    def test_backglass_preferred_over_other(self, machine_model, asset, ct_mm, user):
        """Backglass is chosen even when another category appears first."""
        other_asset = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="playfield.jpg",
            mime_type="image/jpeg",
            byte_size=2048,
            width=400,
            height=300,
            uploaded_by=user,
        )
        em_playfield = _attach(ct_mm, machine_model, other_asset, category="playfield")
        em_backglass = _attach(ct_mm, machine_model, asset, category="backglass")
        # Playfield listed first to test preference logic.
        primary_media = [em_playfield, em_backglass]

        thumb, hero = extract_image_urls({}, primary_media)

        assert thumb == _expected_thumb(asset)
        assert hero == _expected_hero(asset)

    def test_uploaded_wins_over_external(self, machine_model, asset, ct_mm):
        """Uploaded media takes precedence even when extra_data has images."""
        em = _attach(ct_mm, machine_model, asset, category="backglass")
        primary_media = [em]

        thumb, hero = extract_image_urls(OPDB_EXTRA_DATA, primary_media)

        assert thumb == _expected_thumb(asset)
        assert hero == _expected_hero(asset)

    def test_failed_asset_not_in_primary_media(self, machine_model, ct_mm):
        """Failed assets are excluded by the queryset filter, so primary_media
        is empty and we fall through to external."""
        # In the real queryset, failed assets are filtered out by
        # asset__status="ready". Here we simulate that by passing an empty list.
        thumb, hero = extract_image_urls(OPDB_EXTRA_DATA, primary_media=[])

        assert thumb == "https://img.opdb.org/m.jpg"
        assert hero == "https://img.opdb.org/l.jpg"

    def test_no_uploaded_no_external(self):
        thumb, hero = extract_image_urls({}, primary_media=[])

        assert thumb is None
        assert hero is None

    def test_no_primary_media_param_uses_external(self):
        """When primary_media is None, falls through to external."""
        thumb, hero = extract_image_urls(OPDB_EXTRA_DATA, None)

        assert thumb == "https://img.opdb.org/m.jpg"
        assert hero == "https://img.opdb.org/l.jpg"

    def test_relative_urls_are_skipped(self):
        """Image URLs that aren't absolute should be treated as missing."""
        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {"small": "s.jpg", "medium": "m.jpg", "large": "l.jpg"},
                }
            ],
            "opdb.images.__permissiveness_rank": 50,
        }
        thumb, hero = extract_image_urls(extra_data, primary_media=[])

        assert thumb is None
        assert hero is None


# ---------------------------------------------------------------------------
# extract_image_attribution — uploaded vs external
# ---------------------------------------------------------------------------


class TestImageAttribution:
    def test_uploaded_media_returns_none(self, machine_model, asset, ct_mm):
        em = _attach(ct_mm, machine_model, asset, category="backglass")
        primary_media = [em]

        attr = extract_image_attribution(OPDB_EXTRA_DATA, primary_media)

        assert attr is None

    def test_external_media_returns_attribution(self):
        attr = extract_image_attribution(OPDB_EXTRA_DATA, primary_media=[])

        assert attr is not None
        assert attr.license_slug == "cc-by-sa-4-0"

    def test_no_media_returns_none(self):
        attr = extract_image_attribution({}, primary_media=[])

        assert attr is None


# ---------------------------------------------------------------------------
# License gating — uploaded media bypasses, external respects threshold
# ---------------------------------------------------------------------------


class TestLicenseGating:
    def test_uploaded_ignores_license_policy(self, machine_model, asset, ct_mm):
        """Uploaded media is always shown regardless of Constance policy."""
        em = _attach(ct_mm, machine_model, asset, category="backglass")
        primary_media = [em]

        with override_config(CONTENT_DISPLAY_POLICY="licensed-only"):
            thumb, hero = extract_image_urls({}, primary_media)

        assert thumb == _expected_thumb(asset)
        assert hero == _expected_hero(asset)

    def test_external_blocked_by_policy(self):
        """External images below threshold are hidden."""
        extra_data = {
            "opdb.images": [
                {
                    "primary": True,
                    "urls": {
                        "medium": "https://img.opdb.org/m.jpg",
                        "large": "https://img.opdb.org/l.jpg",
                    },
                }
            ],
            "opdb.images.__permissiveness_rank": 0,
        }
        with override_config(CONTENT_DISPLAY_POLICY="licensed-only"):
            thumb, hero = extract_image_urls(extra_data, primary_media=[])

        assert thumb is None
        assert hero is None


# ---------------------------------------------------------------------------
# Integration: API endpoint returns uploaded media URLs
# ---------------------------------------------------------------------------


class TestModelDetailApiResponse:
    """Hit the actual API endpoint and verify image URLs come from uploaded media."""

    @pytest.fixture
    def client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_detail_uses_uploaded_media(self, client, machine_model, asset, ct_mm):
        _attach(ct_mm, machine_model, asset, category="backglass")

        resp = client.get(f"/api/pages/model/{machine_model.public_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["thumbnail_url"] == _expected_thumb(asset)
        assert data["hero_image_url"] == _expected_hero(asset)
        assert data["image_attribution"] is None

    def test_detail_uploaded_media_list(
        self, client, machine_model, asset, ct_mm, user
    ):
        """Detail response includes all uploaded media, not just primary."""
        _attach(ct_mm, machine_model, asset, category="backglass", is_primary=True)
        second = MediaAsset.objects.create(
            kind=MediaAsset.Kind.IMAGE,
            status=MediaAsset.Status.READY,
            original_filename="playfield.jpg",
            mime_type="image/jpeg",
            byte_size=2048,
            width=400,
            height=300,
            uploaded_by=user,
        )
        _attach(ct_mm, machine_model, second, category="playfield", is_primary=False)

        resp = client.get(f"/api/pages/model/{machine_model.public_id}")

        assert resp.status_code == 200
        data = resp.json()
        media = data["uploaded_media"]
        assert len(media) == 2
        uuids = {m["asset_uuid"] for m in media}
        assert str(asset.uuid) in uuids
        assert str(second.uuid) in uuids
        # Verify structure
        for item in media:
            assert "renditions" in item
            assert "thumb" in item["renditions"]
            assert "display" in item["renditions"]
            assert "category" in item
            assert "is_primary" in item
            assert item["uploaded_by_username"] == user.username

    def test_detail_uploaded_media_empty(self, client, machine_model):
        resp = client.get(f"/api/pages/model/{machine_model.public_id}")

        assert resp.status_code == 200
        assert resp.json()["uploaded_media"] == []

    def test_detail_falls_back_to_external(self, client, machine_model):
        machine_model.extra_data = OPDB_EXTRA_DATA
        machine_model.save(update_fields=["extra_data"])

        resp = client.get(f"/api/pages/model/{machine_model.public_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["thumbnail_url"] == "https://img.opdb.org/m.jpg"
        assert data["hero_image_url"] == "https://img.opdb.org/l.jpg"
        assert data["image_attribution"]["license_slug"] == "cc-by-sa-4-0"


class TestModelListApiResponse:
    @pytest.fixture
    def client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_list_uses_uploaded_media(self, client, machine_model, asset, ct_mm):
        _attach(ct_mm, machine_model, asset, category="backglass")

        resp = client.get("/api/models/")

        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]
        match = [i for i in items if i["slug"] == machine_model.slug]
        assert len(match) == 1
        assert match[0]["thumbnail_url"] == _expected_thumb(asset)

    def test_list_falls_back_to_external(self, client, machine_model):
        machine_model.extra_data = OPDB_EXTRA_DATA
        machine_model.save(update_fields=["extra_data"])

        resp = client.get("/api/models/")

        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]
        match = [i for i in items if i["slug"] == machine_model.slug]
        assert len(match) == 1
        assert match[0]["thumbnail_url"] == "https://img.opdb.org/m.jpg"
