"""Tests for database-level constraints on media models.

Uses objects.create() rather than raw SQL — Django's create() bypasses
full_clean(), so invalid values reach the DB and hit CHECK/UNIQUE constraints
directly.
"""

import uuid as uuid_lib

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from apps.media.models import EntityMedia, MediaAsset, MediaRendition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_kwargs(user, **overrides):
    """Return valid MediaAsset kwargs. Override specific fields per test."""
    defaults = {
        "kind": "image",
        "original_filename": "photo.jpg",
        "mime_type": "image/jpeg",
        "byte_size": 5000,
        "width": 800,
        "height": 600,
        "status": "ready",
        "uploaded_by": user,
    }
    defaults.update(overrides)
    return defaults


def _rendition_kwargs(asset, **overrides):
    """Return valid MediaRendition kwargs."""
    defaults = {
        "asset": asset,
        "rendition_type": "original",
        "mime_type": "image/jpeg",
        "byte_size": 5000,
        "width": 800,
        "height": 600,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def asset(user):
    return MediaAsset.objects.create(**_asset_kwargs(user))


@pytest.fixture
def content_type(db):
    """Any ContentType works — GenericFK doesn't enforce referential integrity."""
    return ContentType.objects.get_for_model(MediaAsset)


# ---------------------------------------------------------------------------
# MediaAsset constraints
# ---------------------------------------------------------------------------


class TestMediaAssetConstraints:
    def test_valid_image_asset(self, user):
        asset = MediaAsset.objects.create(**_asset_kwargs(user))
        assert asset.pk is not None

    def test_valid_asset_without_dimensions(self, user):
        """Non-ready assets can omit dimensions."""
        asset = MediaAsset.objects.create(
            **_asset_kwargs(user, status="failed", width=None, height=None)
        )
        assert asset.pk is not None

    def test_blank_original_filename_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, original_filename=""))

    def test_blank_mime_type_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, mime_type=""))

    def test_filename_without_extension_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, original_filename="noext"))

    def test_byte_size_zero_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, byte_size=0))

    def test_invalid_kind_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, kind="audio"))

    def test_invalid_status_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, status="pending"))

    def test_width_without_height_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, width=100, height=None))

    def test_height_without_width_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, width=None, height=100))

    def test_width_zero_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, width=0, height=100))

    def test_height_zero_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(**_asset_kwargs(user, width=100, height=0))

    def test_ready_image_without_dimensions_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(
                **_asset_kwargs(
                    user, status="ready", kind="image", width=None, height=None
                )
            )

    def test_image_processing_status_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(
                **_asset_kwargs(user, kind="image", status="processing")
            )

    def test_image_with_video_mime_type_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(
                **_asset_kwargs(user, kind="image", mime_type="video/mp4")
            )

    def test_video_with_image_mime_type_rejected(self, user):
        with pytest.raises(IntegrityError):
            MediaAsset.objects.create(
                **_asset_kwargs(
                    user,
                    kind="video",
                    status="processing",
                    mime_type="image/jpeg",
                    width=None,
                    height=None,
                )
            )


# ---------------------------------------------------------------------------
# MediaRendition constraints
# ---------------------------------------------------------------------------


class TestMediaRenditionConstraints:
    def test_valid_rendition(self, asset):
        rendition = MediaRendition.objects.create(**_rendition_kwargs(asset))
        assert rendition.pk is not None

    def test_valid_rendition_without_dimensions(self, asset):
        rendition = MediaRendition.objects.create(
            **_rendition_kwargs(asset, width=None, height=None)
        )
        assert rendition.pk is not None

    def test_blank_rendition_type_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(**_rendition_kwargs(asset, rendition_type=""))

    def test_blank_mime_type_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(**_rendition_kwargs(asset, mime_type=""))

    def test_byte_size_zero_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(**_rendition_kwargs(asset, byte_size=0))

    def test_width_without_height_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(
                **_rendition_kwargs(asset, width=100, height=None)
            )

    def test_height_without_width_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(
                **_rendition_kwargs(asset, width=None, height=100)
            )

    def test_width_zero_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(
                **_rendition_kwargs(asset, width=0, height=100)
            )

    def test_uuid_auto_generated(self, asset):
        rendition = MediaRendition.objects.create(**_rendition_kwargs(asset))
        assert rendition.uuid is not None
        assert isinstance(rendition.uuid, uuid_lib.UUID)

    def test_uuid_unique(self, user):
        """Two renditions cannot share a uuid."""
        asset1 = MediaAsset.objects.create(**_asset_kwargs(user))
        asset2 = MediaAsset.objects.create(**_asset_kwargs(user))
        shared_uuid = uuid_lib.uuid4()
        MediaRendition.objects.create(
            **_rendition_kwargs(asset1, rendition_type="thumb", uuid=shared_uuid)
        )
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(
                **_rendition_kwargs(asset2, rendition_type="thumb", uuid=shared_uuid)
            )

    def test_invalid_rendition_type_rejected(self, asset):
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(
                **_rendition_kwargs(asset, rendition_type="poster")
            )

    def test_duplicate_asset_rendition_type_rejected(self, asset):
        MediaRendition.objects.create(
            **_rendition_kwargs(asset, rendition_type="thumb")
        )
        with pytest.raises(IntegrityError):
            MediaRendition.objects.create(
                **_rendition_kwargs(asset, rendition_type="thumb")
            )


# ---------------------------------------------------------------------------
# EntityMedia constraints
# ---------------------------------------------------------------------------


class TestEntityMediaConstraints:
    def test_valid_entity_media(self, asset, content_type):
        em = EntityMedia.objects.create(
            asset=asset, content_type=content_type, object_id=1
        )
        assert em.pk is not None

    def test_valid_two_primaries_different_categories(self, user, content_type):
        """Two primaries on the same entity are fine if categories differ."""
        asset1 = MediaAsset.objects.create(**_asset_kwargs(user))
        asset2 = MediaAsset.objects.create(**_asset_kwargs(user))
        EntityMedia.objects.create(
            asset=asset1,
            content_type=content_type,
            object_id=1,
            category="backglass",
            is_primary=True,
        )
        em2 = EntityMedia.objects.create(
            asset=asset2,
            content_type=content_type,
            object_id=1,
            category="playfield",
            is_primary=True,
        )
        assert em2.pk is not None

    def test_valid_non_primary_same_category(self, user, content_type):
        """Multiple non-primary attachments in the same category are fine."""
        asset1 = MediaAsset.objects.create(**_asset_kwargs(user))
        asset2 = MediaAsset.objects.create(**_asset_kwargs(user))
        EntityMedia.objects.create(
            asset=asset1,
            content_type=content_type,
            object_id=1,
            category="backglass",
            is_primary=False,
        )
        em2 = EntityMedia.objects.create(
            asset=asset2,
            content_type=content_type,
            object_id=1,
            category="backglass",
            is_primary=False,
        )
        assert em2.pk is not None

    def test_duplicate_asset_same_entity_rejected(self, asset, content_type):
        EntityMedia.objects.create(asset=asset, content_type=content_type, object_id=1)
        with pytest.raises(IntegrityError):
            EntityMedia.objects.create(
                asset=asset, content_type=content_type, object_id=1
            )

    def test_same_asset_different_entity_rejected(self, asset, content_type):
        """Each asset belongs to exactly one entity."""
        EntityMedia.objects.create(asset=asset, content_type=content_type, object_id=1)
        with pytest.raises(IntegrityError):
            EntityMedia.objects.create(
                asset=asset, content_type=content_type, object_id=2
            )

    def test_two_primaries_same_category_allowed(self, user, content_type):
        """is_primary stores the raw claim, so two primaries in one category are
        allowed at the DB level — the displayed primary is chosen at read time."""
        asset1 = MediaAsset.objects.create(**_asset_kwargs(user))
        asset2 = MediaAsset.objects.create(**_asset_kwargs(user))
        EntityMedia.objects.create(
            asset=asset1,
            content_type=content_type,
            object_id=1,
            category="backglass",
            is_primary=True,
        )
        em2 = EntityMedia.objects.create(
            asset=asset2,
            content_type=content_type,
            object_id=1,
            category="backglass",
            is_primary=True,
        )
        assert em2.pk is not None

    def test_two_uncategorized_primaries_allowed(self, user, content_type):
        """Raw primaries with null category are likewise allowed."""
        asset1 = MediaAsset.objects.create(**_asset_kwargs(user))
        asset2 = MediaAsset.objects.create(**_asset_kwargs(user))
        EntityMedia.objects.create(
            asset=asset1,
            content_type=content_type,
            object_id=1,
            category=None,
            is_primary=True,
        )
        em2 = EntityMedia.objects.create(
            asset=asset2,
            content_type=content_type,
            object_id=1,
            category=None,
            is_primary=True,
        )
        assert em2.pk is not None

    def test_blank_category_rejected(self, asset, content_type):
        with pytest.raises(IntegrityError):
            EntityMedia.objects.create(
                asset=asset,
                content_type=content_type,
                object_id=1,
                category="",
            )

    def test_object_id_zero_rejected(self, asset, content_type):
        with pytest.raises(IntegrityError):
            EntityMedia.objects.create(
                asset=asset,
                content_type=content_type,
                object_id=0,
            )
