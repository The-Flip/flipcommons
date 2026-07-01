"""Characterization of media mutations through the shared claim write path.

Pins the observable behavior of the four media endpoints (upload / detach /
set-primary / set-category). These endpoints write media attachment claims
through ``execute_claims`` and use the generic ``resolve_after_mutation``
dispatch, so this suite proves the materialized result (``EntityMedia`` rows,
primary flag, category) and the entity's own scalar columns are unperturbed.

Both a MachineModel target and a Manufacturer target are exercised through the
same generic per-entity path. Entities are seeded so every scalar field is
claim-backed — modeling production, where re-resolution is a no-op — so the
scalar-snapshot assertion isolates "the wider re-resolution perturbs nothing".

The error path is pinned separately (per-endpoint status) in
``test_media_single_path_errors``.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.test import Client

from apps.catalog.models import Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.media.models import EntityMedia, MediaAsset
from apps.provenance.models import CitationInstance, Source
from apps.provenance.test_factories import make_claim

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


@dataclass(frozen=True)
class MediaTarget:
    """A media-supported entity plus the two categories its tests use."""

    entity: Model
    entity_type: str
    public_id: str
    cat1: str
    cat2: str


def _bootstrap_source() -> Source:
    src, _ = Source.objects.get_or_create(
        slug="bootstrap",
        defaults={"name": "Bootstrap", "source_type": "editorial", "priority": 1},
    )
    return src


@pytest.fixture(params=["model", "manufacturer"])
def target(request, db) -> MediaTarget:
    """A resolution-stable media target, parametrized over MachineModel and
    Manufacturer — both resolved through the same generic per-entity path.

    Both are seeded so every scalar claim field is backed, so the scalar
    re-resolution is a no-op and the snapshot assertion measures only "media
    mutation didn't perturb the row".
    """
    if request.param == "model":
        mm = make_machine_model(name="Char Machine", slug="char-machine")
        return MediaTarget(mm, "model", mm.public_id, "backglass", "playfield")

    src = _bootstrap_source()
    mfr = Manufacturer.objects.create(name="Char Mfr", slug="char-mfr", status="active")
    # Back every scalar that re-resolution would otherwise normalize away.
    make_claim(mfr, "name", "Char Mfr", ingest_source=src)
    make_claim(mfr, "slug", "char-mfr", ingest_source=src)
    make_claim(mfr, "status", "active", ingest_source=src)
    return MediaTarget(mfr, "manufacturer", mfr.public_id, "logo", "other")


def _image(name: str = "test.jpg") -> BytesIO:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (100, 100), color="red").save(buf, format="JPEG")
    buf.seek(0)
    buf.name = name
    return buf


def _scalar_snapshot(entity: Model) -> dict[str, object]:
    """Semantic column values of the entity row (FKs as ``*_id``), reloaded.

    Excludes auto-timestamps: routing media through the unified resolver now
    re-saves the entity row (bumping ``updated_at``), which is a benign
    consequence of full re-resolution, not a semantic change. The snapshot
    isolates claim-resolved state so it can assert the media mutation perturbs
    nothing else.
    """
    entity.refresh_from_db()
    return {
        f.attname: getattr(entity, f.attname)
        for f in entity._meta.local_concrete_fields
        if not getattr(f, "auto_now", False) and not getattr(f, "auto_now_add", False)
    }


def _upload(client: Client, target: MediaTarget, category: str) -> MediaAsset:
    resp = client.post(
        UPLOAD_URL,
        data={
            "file": _image(),
            "entity_type": target.entity_type,
            "public_id": target.public_id,
            "category": category,
        },
    )
    assert resp.status_code == 200, resp.content
    return MediaAsset.objects.latest("pk")


def _entity_media(target: MediaTarget) -> EntityMedia:
    ct = ContentType.objects.get_for_model(type(target.entity))
    return EntityMedia.objects.get(content_type=ct, object_id=target.entity.pk)


def _entity_media_for(target: MediaTarget, asset: MediaAsset) -> EntityMedia:
    ct = ContentType.objects.get_for_model(type(target.entity))
    return EntityMedia.objects.get(
        content_type=ct, object_id=target.entity.pk, asset=asset
    )


class TestMediaSinglePathCharacterization:
    def test_upload_materializes_entity_media(self, client, target):
        before = _scalar_snapshot(target.entity)

        asset = _upload(client, target, target.cat1)

        em = _entity_media(target)
        assert em.asset_id == asset.pk
        assert em.category == target.cat1
        # The resolver stores the raw claimed value; auto-promotion of a sole
        # attachment to the displayed primary is a read-time selection.
        assert em.is_primary is False
        # A media mutation never attaches a citation.
        assert (
            CitationInstance.objects.filter(
                claim__field_name="media_attachment"
            ).count()
            == 0
        )
        assert _scalar_snapshot(target.entity) == before

    def test_set_primary_promotes_second_asset(self, client, target):
        _upload(client, target, target.cat1)
        asset2 = _upload(client, target, target.cat1)
        before = _scalar_snapshot(target.entity)

        resp = client.post(
            SET_PRIMARY_URL,
            data={
                "entity_type": target.entity_type,
                "public_id": target.public_id,
                "asset_uuid": str(asset2.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 204, resp.content

        assert _entity_media_for(target, asset2).is_primary is True
        assert _scalar_snapshot(target.entity) == before

    def test_set_category_moves_asset(self, client, target):
        asset = _upload(client, target, target.cat1)
        before = _scalar_snapshot(target.entity)

        resp = client.post(
            SET_CATEGORY_URL,
            data={
                "entity_type": target.entity_type,
                "public_id": target.public_id,
                "asset_uuid": str(asset.uuid),
                "category": target.cat2,
            },
            content_type="application/json",
        )
        assert resp.status_code == 204, resp.content

        assert _entity_media_for(target, asset).category == target.cat2
        assert _scalar_snapshot(target.entity) == before

    def test_detach_removes_entity_media(self, client, target):
        asset = _upload(client, target, target.cat1)
        before = _scalar_snapshot(target.entity)

        resp = client.post(
            DETACH_URL,
            data={
                "entity_type": target.entity_type,
                "public_id": target.public_id,
                "asset_uuid": str(asset.uuid),
            },
            content_type="application/json",
        )
        assert resp.status_code == 204, resp.content

        ct = ContentType.objects.get_for_model(type(target.entity))
        assert not EntityMedia.objects.filter(
            content_type=ct, object_id=target.entity.pk, asset=asset
        ).exists()
        assert _scalar_snapshot(target.entity) == before
