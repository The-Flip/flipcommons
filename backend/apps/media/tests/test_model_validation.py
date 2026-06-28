"""Tests for model-level validation (clean()) on media models."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.media.models import EntityMedia, MediaAsset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_kwargs(user, **overrides):
    """Return valid MediaAsset kwargs."""
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def asset(user):
    return MediaAsset.objects.create(**_asset_kwargs(user))


# ---------------------------------------------------------------------------
# EntityMedia.clean() — content type validation
# ---------------------------------------------------------------------------


class TestEntityMediaContentTypeValidation:
    def test_supported_content_type_accepted(self, asset):
        """MachineModel is MediaSupportedModel, so EntityMedia.clean() passes."""
        from apps.catalog.models import MachineModel

        ct = ContentType.objects.get_for_model(MachineModel)
        em = EntityMedia(asset=asset, content_type=ct, object_id=1)
        em.clean()  # should not raise

    def test_unsupported_content_type_rejected(self, asset):
        """User is not MediaSupportedModel, so EntityMedia.clean() raises."""
        ct = ContentType.objects.get_for_model(User)
        em = EntityMedia(asset=asset, content_type=ct, object_id=1)
        with pytest.raises(ValidationError) as exc_info:
            em.clean()
        assert "content_type" in exc_info.value.message_dict


class TestEntityMediaOrdering:
    def test_default_ordering_follows_local_asset_id(self, user):
        """Default ordering sorts by the local asset_id column, ascending.

        Ordering by the FK *name* ("asset") would inherit MediaAsset's own
        Meta.ordering (-created_at) through an implicit join — reintroducing
        timestamp ordering and reversing the intended lowest-asset_id-first.
        """
        from apps.catalog.models import MachineModel

        ct = ContentType.objects.get_for_model(MachineModel)
        # Created in sequence: ``older`` has both the lower pk and the earlier
        # created_at, so asset_id-ASC and created_at-DESC yield opposite orders.
        older = MediaAsset.objects.create(**_asset_kwargs(user))
        newer = MediaAsset.objects.create(**_asset_kwargs(user))
        # Insert the rows in reverse so a fallback to EntityMedia.id would also
        # produce the wrong order.
        for asset in (newer, older):
            EntityMedia.objects.create(asset=asset, content_type=ct, object_id=1)

        rows = list(EntityMedia.objects.filter(content_type=ct, object_id=1))
        assert [em.asset_id for em in rows] == [older.pk, newer.pk]
