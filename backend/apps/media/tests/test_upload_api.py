"""Tests for the media upload API endpoint."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from django.test import Client

from apps.accounts.test_factories import make_user
from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import MediaAsset, MediaRendition

# All upload tests use InMemoryStorage — no filesystem, no S3.
_TEST_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
_TEST_MEDIA_URL = "https://test-media.example.com/"

UPLOAD_URL = "/api/media/upload/"

pytestmark = pytest.mark.django_db


def _only_asset() -> MediaAsset:
    asset = MediaAsset.objects.first()
    assert asset is not None
    return asset


def _create_test_image(
    width: int = 100,
    height: int = 100,
    fmt: str = "JPEG",
    name: str = "test.jpg",
) -> BytesIO:
    """Create a valid image file suitable for Django upload testing."""
    from PIL import Image

    mode = "RGBA" if fmt == "PNG" else "RGB"
    img = Image.new(mode, (width, height), color="red")
    buf = BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    buf.name = name
    return buf


def _create_bmp_image(name: str = "legacy.bmp") -> BytesIO:
    from PIL import Image

    img = Image.new("RGB", (100, 100), color="blue")
    buf = BytesIO()
    img.save(buf, format="BMP")
    buf.seek(0)
    buf.name = name
    return buf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _media_settings(settings):
    """Apply InMemoryStorage + test media URL to all tests in this module."""
    settings.STORAGES = _TEST_STORAGE
    settings.MEDIA_PUBLIC_BASE_URL = _TEST_MEDIA_URL
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def machine_model(db):
    return make_machine_model(name="Test Machine", slug="test-machine")


def _post_upload(client, machine_model, file=None, **extra):
    """Helper to POST a file upload with default attachment metadata."""
    if file is None:
        file = _create_test_image()
    data = {
        "file": file,
        "entity_type": "model",
        "public_id": machine_model.public_id,
        "category": "backglass",
        **extra,
    }
    return client.post(UPLOAD_URL, data, format="multipart")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestUploadHappyPath:
    def test_upload_valid_jpeg(self, client, machine_model):
        resp = _post_upload(client, machine_model)
        assert resp.status_code == 200

        body = resp.json()
        assert body["kind"] == "image"
        assert body["status"] == "ready"
        assert body["original_filename"] == "test.jpg"
        assert body["width"] == 100
        assert body["height"] == 100

        # DB rows created
        assert MediaAsset.objects.count() == 1
        assert MediaRendition.objects.count() == 3

        asset = _only_asset()
        types = set(asset.renditions.values_list("rendition_type", flat=True))
        assert types == {"original", "thumb", "display"}

    def test_upload_png_with_transparency(self, client, machine_model):
        file = _create_test_image(fmt="PNG", name="alpha.png")
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 200

        asset = _only_asset()
        original_rendition = asset.renditions.get(rendition_type="original")
        # PNG with alpha stays PNG
        assert original_rendition.mime_type == "image/png"

        # Thumb and display are always WebP
        thumb = asset.renditions.get(rendition_type="thumb")
        assert thumb.mime_type == "image/webp"

    def test_upload_returns_rendition_urls(self, client, machine_model):
        resp = _post_upload(client, machine_model)
        body = resp.json()

        renditions = body["renditions"]
        assert renditions["original"].startswith(_TEST_MEDIA_URL)
        assert renditions["thumb"].startswith(_TEST_MEDIA_URL)
        assert renditions["display"].startswith(_TEST_MEDIA_URL)
        assert renditions["thumb"].endswith("/thumb")
        assert renditions["display"].endswith("/display")

    def test_upload_bmp_converted(self, client, machine_model):
        file = _create_bmp_image()
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 200

        asset = _only_asset()
        original_rendition = asset.renditions.get(rendition_type="original")
        # BMP converted to JPEG
        assert original_rendition.mime_type == "image/jpeg"

        # Asset mime_type and byte_size both describe the stored original,
        # not the raw upload — they must be consistent.
        assert asset.mime_type == "image/jpeg"
        assert asset.byte_size == original_rendition.byte_size

        # Storage key is extensionless — Content-Type is in object metadata
        body = resp.json()
        assert body["renditions"]["original"].endswith("/original")

    def test_upload_unicode_filename_preserved(self, client, machine_model):
        file = _create_test_image(name="café (1).jpg")
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 200

        body = resp.json()
        # Original filename preserved for display
        assert body["original_filename"] == "café (1).jpg"
        # Storage key is extensionless — no filename sanitization in the key
        assert body["renditions"]["original"].endswith("/original")

    def test_attachment_metadata_echoed(self, client, machine_model):
        resp = _post_upload(client, machine_model)
        body = resp.json()

        attachment = body["attachment"]
        assert attachment["entity_type"] == "model"
        assert attachment["public_id"] == "test-machine"
        assert attachment["category"] == "backglass"
        assert "is_primary" not in attachment

    def test_upload_creates_entity_media(self, client, machine_model):
        """Upload creates claim + EntityMedia with correct attachment metadata."""
        from django.contrib.contenttypes.models import ContentType

        from apps.media.models import EntityMedia
        from apps.provenance.models import Claim

        resp = _post_upload(client, machine_model)
        assert resp.status_code == 200

        # EntityMedia materialized
        em = EntityMedia.objects.get()
        ct = ContentType.objects.get_for_model(type(machine_model))
        assert em.content_type == ct
        assert em.object_id == machine_model.pk
        assert em.category == "backglass"
        # The resolver stores the raw claimed value; a sole image is auto-promoted
        # to the displayed primary at read time.
        assert em.is_primary is False

        # Claim created
        claim = Claim.objects.get(
            content_type=ct,
            object_id=machine_model.pk,
            field_name="media_attachment",
            is_active=True,
        )
        assert claim.value["media_asset"] == em.asset.pk
        assert claim.actor.backing_model == "user"


# ---------------------------------------------------------------------------
# Validation errors (400)
# ---------------------------------------------------------------------------


class TestUploadValidation:
    def test_no_file(self, client, machine_model):
        data = {
            "entity_type": "model",
            "public_id": machine_model.public_id,
        }
        resp = client.post(UPLOAD_URL, data)
        assert resp.status_code == 422  # ninja validation error

    def test_invalid_extension(self, client, machine_model):
        file = BytesIO(b"not an image")
        file.name = "readme.txt"
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"].lower()

    def test_oversized_file(self, client, machine_model, monkeypatch):
        from apps.media.constants import MAX_IMAGE_FILE_SIZE

        file = _create_test_image()
        # Patch read to return oversized data
        monkeypatch.setattr(
            file, "read", lambda *a, **kw: b"\x00" * (MAX_IMAGE_FILE_SIZE + 1)
        )
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 400
        assert "size" in resp.json()["detail"].lower()

    def test_corrupt_image(self, client, machine_model):
        file = BytesIO(b"this is not a valid image at all")
        file.name = "corrupt.jpg"
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 400
        assert "invalid image" in resp.json()["detail"].lower()

    def test_degenerate_dimensions(self, client, machine_model):
        """1x1 image rejected by validate_image (MIN_IMAGE_DIMENSION=2)."""
        file = _create_test_image(width=1, height=1, name="tiny.jpg")
        resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 400

    def test_unknown_entity_type(self, client, machine_model):
        file = _create_test_image()
        resp = _post_upload(client, machine_model, file=file, entity_type="spaceship")
        assert resp.status_code == 404
        assert "unknown entity_type" in resp.json()["detail"].lower()

    def test_entity_type_not_media_supported(self, client, machine_model):
        """A real catalog model that doesn't inherit MediaSupportedModel."""
        file = _create_test_image()
        # Title exists in catalog but doesn't inherit MediaSupportedModel
        from apps.catalog.models import Title

        Title.objects.create(name="Test Title", slug="test-title")
        resp = _post_upload(
            client,
            machine_model,
            file=file,
            entity_type="title",
            public_id="test-title",
        )
        assert resp.status_code == 400
        assert "does not support media" in resp.json()["detail"].lower()

    def test_entity_not_found(self, client, machine_model):
        file = _create_test_image()
        resp = _post_upload(
            client, machine_model, file=file, public_id="nonexistent-slug"
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    def test_invalid_category(self, client, machine_model):
        file = _create_test_image()
        resp = _post_upload(client, machine_model, file=file, category="nonexistent")
        assert resp.status_code == 400
        assert "invalid category" in resp.json()["detail"].lower()

    def test_codec_unavailable(self, client, machine_model):
        """HEIC extension when pillow-heif not installed."""
        file = BytesIO(b"fake heic data")
        file.name = "photo.heic"
        with patch(
            "apps.media.api.check_codec_support",
            return_value={"heic": False, "heif": False, "avif": True},
        ):
            resp = _post_upload(client, machine_model, file=file)
        assert resp.status_code == 400
        assert "not supported" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Auth (401)
# ---------------------------------------------------------------------------


class TestUploadAuth:
    def test_anonymous_rejected(self, db, machine_model):
        anon_client = Client()  # not logged in
        file = _create_test_image()
        data = {
            "file": file,
            "entity_type": "model",
            "public_id": machine_model.public_id,
        }
        resp = anon_client.post(UPLOAD_URL, data)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting (429)
# ---------------------------------------------------------------------------


class TestUploadRateLimit:
    def test_rate_limit_exceeded(self, client, machine_model, user):
        from django.core.cache import cache

        cache.set(f"media_upload_count:{user.pk}", 60, 3600)

        resp = _post_upload(client, machine_model)
        assert resp.status_code == 429
        assert "limit" in resp.json()["detail"].lower()

    def test_rate_limit_per_user(self, db, machine_model):
        """Different users have independent limits."""
        from django.core.cache import cache

        user1 = make_user()
        user2 = make_user()

        cache.set(f"media_upload_count:{user1.pk}", 60, 3600)

        c2 = Client()
        c2.force_login(user2)
        resp = _post_upload(c2, machine_model)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


class TestUploadAtomicity:
    def test_storage_failure_no_db_rows(self, client, machine_model):
        """If storage fails mid-upload, no DB rows should exist."""
        call_count = 0
        from apps.media.storage import upload_to_storage as real_upload

        def failing_upload(key, data, content_type):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # fail on second file (thumb)
                raise OSError("Simulated S3 failure")
            return real_upload(key, data, content_type)

        client.raise_request_exception = False
        with patch("apps.media.api.upload_to_storage", side_effect=failing_upload):
            file = _create_test_image()
            resp = _post_upload(client, machine_model, file=file)

        assert resp.status_code == 500
        assert MediaAsset.objects.count() == 0
        assert MediaRendition.objects.count() == 0

    def test_storage_failure_reaches_sentry(
        self, client, machine_model, sentry_recording
    ):
        """A storage fault propagates: Sentry gets the event, the client a 500."""
        client.raise_request_exception = False
        with (
            patch(
                "apps.media.api.upload_to_storage",
                side_effect=OSError("Simulated S3 failure"),
            ),
            patch("apps.media.api.delete_from_storage", return_value=[]),
        ):
            resp = _post_upload(client, machine_model)

        assert resp.status_code == 500
        assert [
            e["exception"]["values"][-1]["type"] for e in sentry_recording.events
        ] == ["OSError"]
        # The view's locals hold the raw upload; no frame may carry them.
        frames = [
            frame
            for event in sentry_recording.events
            for value in event["exception"]["values"]
            for frame in value["stacktrace"]["frames"]
        ]
        assert frames
        assert all("vars" not in frame for frame in frames)

    def test_db_failure_cleans_storage(self, client, machine_model):
        """If DB transaction fails after S3 upload, storage should be cleaned."""
        client.raise_request_exception = False
        with (
            patch("apps.media.api.delete_from_storage", return_value=[]) as mock_delete,
            patch(
                "apps.media.api.MediaAsset.objects.create",
                side_effect=Exception("Simulated DB failure"),
            ),
        ):
            file = _create_test_image()
            resp = _post_upload(client, machine_model, file=file)

            assert resp.status_code == 500
            # Verify cleanup was called with the 3 uploaded keys
            mock_delete.assert_called_once()
            deleted_keys = mock_delete.call_args[0][0]
            assert len(deleted_keys) == 3

        # Outside the mock context — real count
        assert MediaAsset.objects.count() == 0
