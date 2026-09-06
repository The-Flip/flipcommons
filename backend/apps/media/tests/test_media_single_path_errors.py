"""Uniform per-endpoint error contract for media writes through execute_claims.

All four media endpoints surface a client-fault claim-write failure
(``execute_claims``'s ``StructuredValidationError``, raised on ``IntegrityError``
/ ``ValidationError``) as a 422:

- ``detach`` / ``set-primary`` / ``set-category`` have no try/except around their
  atomic block, so it propagates straight to Ninja's 422 handler.
- ``upload`` wraps its DB work so it can delete the storage blobs it already
  uploaded; a dedicated ``except StructuredValidationError`` cleans up and
  re-raises (→ 422), while the broad ``except Exception`` still maps an
  unexpected failure to a 500 (also cleaning up).

A forced mint failure pins both behaviors.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pytest
from django.db import IntegrityError
from django.test import Client

from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import MediaAsset

_TEST_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

UPLOAD_URL = "/api/media/upload/"
DETACH_URL = "/api/media/detach/"
SET_PRIMARY_URL = "/api/media/set-primary/"
SET_CATEGORY_URL = "/api/media/set-category/"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_settings(settings):
    settings.STORAGES = _TEST_STORAGE
    settings.MEDIA_PUBLIC_BASE_URL = "https://test-media.example.com/"
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def machine_model(db):
    return make_machine_model(name="Err Machine", slug="err-machine")


def _image() -> BytesIO:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (100, 100), color="red").save(buf, format="JPEG")
    buf.seek(0)
    buf.name = "test.jpg"
    return buf


def _upload(client: Client, machine_model, category: str = "backglass") -> MediaAsset:
    resp = client.post(
        UPLOAD_URL,
        data={
            "file": _image(),
            "entity_type": "model",
            "public_id": machine_model.public_id,
            "category": category,
        },
    )
    assert resp.status_code == 200, resp.content
    return MediaAsset.objects.latest("pk")


def _break_mint(monkeypatch) -> None:
    """Force the claim-mint primitive execute_claims uses to raise IntegrityError.

    Patches the name as bound into ``claim_write`` (where execute_claims looks it
    up), so execute_claims's IntegrityError→StructuredValidationError translation
    runs.
    """

    def boom(*args, **kwargs):
        raise IntegrityError("forced mint failure")

    monkeypatch.setattr("apps.claim_edit.claim_write._assert_claim", boom)


class TestMutationEndpointsReturn422:
    """The three endpoints with no storage-cleanup wrapper surface a 422."""

    def test_detach_returns_422(self, client, machine_model, monkeypatch):
        asset = _upload(client, machine_model)
        _break_mint(monkeypatch)
        resp = client.post(
            DETACH_URL,
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 422, resp.content

    def test_set_primary_returns_422(self, client, machine_model, monkeypatch):
        asset = _upload(client, machine_model)
        _break_mint(monkeypatch)
        resp = client.post(
            SET_PRIMARY_URL,
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 422, resp.content

    def test_set_category_returns_422(self, client, machine_model, monkeypatch):
        asset = _upload(client, machine_model, category="backglass")
        _break_mint(monkeypatch)
        resp = client.post(
            SET_CATEGORY_URL,
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
                "category": "playfield",
            },
            content_type="application/json",
        )
        assert resp.status_code == 422, resp.content


class TestUploadSurfaces422:
    def test_upload_returns_422_and_cleans_up_storage(
        self, client, machine_model, monkeypatch
    ):
        """A client-fault claim failure surfaces as 422, blobs still cleaned up.

        Upload's storage-cleanup ``except`` no longer masks the
        ``StructuredValidationError`` as a 500 — it cleans up and re-raises, so
        the error contract matches the other three endpoints.
        """
        deleted: list[list[str]] = []

        def record_delete(keys):
            deleted.append(list(keys))

        monkeypatch.setattr("apps.media.api.delete_from_storage", record_delete)
        _break_mint(monkeypatch)

        resp = client.post(
            UPLOAD_URL,
            data={
                "file": _image(),
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "category": "backglass",
            },
        )

        assert resp.status_code == 422, resp.content
        # The dedicated except still cleaned up the blobs uploaded before the failure.
        assert deleted, "delete_from_storage was not called on failure"
        assert deleted[-1], "uploaded storage keys were not cleaned up"


class TestUploadCleanupLeak:
    def test_leak_after_422_reaches_sentry(
        self, client, machine_model, monkeypatch, sentry_recording
    ):
        """The 422's parent exception is filtered from Sentry, so a leak here
        would otherwise never be reported."""
        broken_storage = MagicMock()
        broken_storage.save.side_effect = lambda key, content: key
        broken_storage.delete.side_effect = OSError("bucket unreachable")
        monkeypatch.setattr(
            "apps.media.storage.get_media_storage", lambda: broken_storage
        )
        _break_mint(monkeypatch)

        resp = client.post(
            UPLOAD_URL,
            data={
                "file": _image(),
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "category": "backglass",
            },
        )

        assert resp.status_code == 422, resp.content
        assert [
            e["exception"]["values"][-1]["type"] for e in sentry_recording.events
        ] == ["MediaStorageLeakError"]
