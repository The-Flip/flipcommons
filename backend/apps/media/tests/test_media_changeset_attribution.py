"""Every MEDIA_EDIT mutation must attribute its claim to a user ChangeSet.

Regression for the Actors "Fix Media Claims" leak: the four media endpoints
(upload/attach, detach, set-primary, set-category) minted user claims via
``assert_claim`` with no ``changeset``, leaving them unattributed. Each
mutation must now open a user-attributed ChangeSet (``action=EDIT``) and link
its claim to it.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import Client

from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import MediaAsset
from apps.provenance.models import ChangeSetAction, Claim

# Upload needs storage; reuse the in-memory backend the upload tests use.
_TEST_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

UPLOAD_URL = "/api/media/upload/"

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
    return make_machine_model(name="Test Machine", slug="test-machine")


def _image(name: str = "test.jpg") -> BytesIO:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (100, 100), color="red").save(buf, format="JPEG")
    buf.seek(0)
    buf.name = name
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
    asset = MediaAsset.objects.latest("pk")
    return asset


def _latest_active_media_claim(machine_model) -> Claim:
    ct = ContentType.objects.get_for_model(type(machine_model))
    return Claim.objects.filter(
        content_type=ct,
        object_id=machine_model.pk,
        field_name="media_attachment",
        is_active=True,
    ).latest("created_at")


def _assert_attributed(claim: Claim, user) -> None:
    cs = claim.changeset
    assert cs is not None, "media claim was minted with no ChangeSet"
    assert cs.user_id == user.id
    assert cs.action == ChangeSetAction.EDIT


class TestMediaMutationsAreAttributed:
    def test_upload_attaches_with_changeset(self, client, machine_model, user):
        _upload(client, machine_model)
        _assert_attributed(_latest_active_media_claim(machine_model), user)

    def test_detach_records_changeset(self, client, machine_model, user):
        asset = _upload(client, machine_model)
        resp = client.post(
            "/api/media/detach/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 204
        # The detach tombstone (exists=False) is the active claim now.
        claim = _latest_active_media_claim(machine_model)
        assert claim.value.get("exists") is False
        _assert_attributed(claim, user)

    def test_set_primary_records_changeset(self, client, machine_model, user):
        _upload(client, machine_model, category="backglass")
        asset2 = _upload(client, machine_model, category="backglass")
        resp = client.post(
            "/api/media/set-primary/",
            data={
                "entity_type": "model",
                "public_id": machine_model.public_id,
                "asset_uuid": str(asset2.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 204
        _assert_attributed(_latest_active_media_claim(machine_model), user)

    def test_set_category_records_changeset(self, client, machine_model, user):
        asset = _upload(client, machine_model, category="backglass")
        resp = client.post(
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
        _assert_attributed(_latest_active_media_claim(machine_model), user)
