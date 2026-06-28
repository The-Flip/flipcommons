"""Tests for media_attachment claims, resolution, and primary enforcement.

Written TDD-style: these tests define the contract for the resolver
(``catalog/resolve/_media.py``) before the implementation exists.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from apps.catalog.claims import build_media_attachment_claim
from apps.catalog.models import MachineModel
from apps.catalog.tests.conftest import make_machine_model
from apps.media.helpers import displayed_primary_asset_ids
from apps.media.models import EntityMedia, MediaAsset
from apps.provenance.models import Source
from apps.provenance.test_factories import make_claim, user_changeset

User = get_user_model()

pytestmark = pytest.mark.django_db


def _assert_claim(subject, field_name, value, *, user=None, source=None, claim_key=""):
    """``assert_claim`` wrapper that opens a throwaway user ChangeSet (tests only).

    User-attributed claims now require a changeset; these resolver tests don't
    care which one, so each user call gets a fresh ``EDIT`` changeset. Source
    calls pass through unchanged.
    """
    changeset = user_changeset(user) if user is not None else None
    return make_claim(
        subject,
        field_name,
        value,
        user=user,
        source=source,
        claim_key=claim_key,
        changeset=changeset,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def source(db):
    return Source.objects.create(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def high_source(db):
    return Source.objects.create(
        name="Editorial", source_type="editorial", priority=100
    )


@pytest.fixture
def machine_model(db):
    return make_machine_model(name="Test Machine", slug="test-machine")


@pytest.fixture
def asset(db, user):
    """A ready image MediaAsset for claim tests."""
    return MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        original_filename="test.jpg",
        mime_type="image/jpeg",
        byte_size=1024,
        width=100,
        height=100,
        uploaded_by=user,
    )


@pytest.fixture
def asset2(db, user):
    """A second MediaAsset for multi-attachment tests."""
    return MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=MediaAsset.Status.READY,
        original_filename="test2.jpg",
        mime_type="image/jpeg",
        byte_size=2048,
        width=200,
        height=200,
        uploaded_by=user,
    )


def _resolve_media(entity):
    """Call the media resolver scoped to a single entity."""
    from apps.catalog.resolve import resolve_media_attachments

    ct = ContentType.objects.get_for_model(entity)
    resolve_media_attachments(content_type_id=ct.id, subject_ids={entity.pk})


def _displayed_primaries(entity):
    """Asset ids selected as displayed primary for *entity* (read-time rule)."""
    ct = ContentType.objects.get_for_model(entity)
    return displayed_primary_asset_ids(
        EntityMedia.objects.filter(content_type=ct, object_id=entity.pk)
    )


# ---------------------------------------------------------------------------
# build_media_attachment_claim() helper
# ---------------------------------------------------------------------------


class TestBuildMediaAttachmentClaim:
    def test_valid_claim(self, machine_model, asset):
        claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        assert claim_key == f"media_attachment|media_asset:{asset.pk}"
        assert value["media_asset"] == asset.pk
        assert value["category"] == "backglass"
        assert value["is_primary"] is True
        assert value["exists"] is True

    def test_null_category_allowed(self, machine_model, asset):
        _claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, category=None
        )
        assert value["category"] is None

    def test_invalid_category_raises(self, machine_model, asset):
        with pytest.raises(ValueError, match="Invalid category"):
            build_media_attachment_claim(
                machine_model, asset.pk, category="nonexistent"
            )

    def test_retraction(self, machine_model, asset):
        # Tombstone invariant (build_relationship_claim step 8): an exists=False
        # detach claim carries identity (media_asset) + exists only — the inert
        # category/is_primary are dropped. The resolver skips an exists=False
        # claim before it would read them, so this is resolver-inert.
        _claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, exists=False
        )
        assert value == {"media_asset": asset.pk, "exists": False}


# ---------------------------------------------------------------------------
# Claim assertion
# ---------------------------------------------------------------------------


class TestClaimAssertion:
    def test_round_trip(self, machine_model, asset, user):
        claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        claim = _assert_claim(
            machine_model,
            "media_attachment",
            value,
            user=user,
            claim_key=claim_key,
        )
        assert claim.field_name == "media_attachment"
        assert claim.claim_key == claim_key
        assert claim.value == value
        assert claim.is_active is True

    def test_supersession(self, machine_model, asset, user):
        claim_key, value1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass"
        )
        old = _assert_claim(
            machine_model,
            "media_attachment",
            value1,
            user=user,
            claim_key=claim_key,
        )

        _key, value2 = build_media_attachment_claim(
            machine_model, asset.pk, category="playfield"
        )
        new = _assert_claim(
            machine_model,
            "media_attachment",
            value2,
            user=user,
            claim_key=claim_key,
        )

        old.refresh_from_db()
        assert old.is_active is False
        assert new.is_active is True


# ---------------------------------------------------------------------------
# Resolution happy path
# ---------------------------------------------------------------------------


class TestResolutionHappyPath:
    def test_single_claim_materializes(self, machine_model, asset, user):
        claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            value,
            user=user,
            claim_key=claim_key,
        )

        _resolve_media(machine_model)

        em = EntityMedia.objects.get()
        ct = ContentType.objects.get_for_model(MachineModel)
        assert em.content_type == ct
        assert em.object_id == machine_model.pk
        assert em.asset == asset
        assert em.category == "backglass"
        assert em.is_primary is True

    def test_retraction_deletes(self, machine_model, asset, user):
        # First create an attachment
        claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass"
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            value,
            user=user,
            claim_key=claim_key,
        )
        _resolve_media(machine_model)
        assert EntityMedia.objects.count() == 1

        # Retract it
        claim_key, retract_value = build_media_attachment_claim(
            machine_model, asset.pk, exists=False
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            retract_value,
            user=user,
            claim_key=claim_key,
        )
        _resolve_media(machine_model)
        assert EntityMedia.objects.count() == 0

    def test_update_category(self, machine_model, asset, user):
        claim_key, value = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass"
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            value,
            user=user,
            claim_key=claim_key,
        )
        _resolve_media(machine_model)
        assert EntityMedia.objects.get().category == "backglass"

        # Supersede with new category
        _key, new_value = build_media_attachment_claim(
            machine_model, asset.pk, category="playfield"
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            new_value,
            user=user,
            claim_key=claim_key,
        )
        _resolve_media(machine_model)
        em = EntityMedia.objects.get()
        assert em.category == "playfield"

    def test_update_is_primary(self, machine_model, asset, asset2, user):
        """Explicit is_primary=True on a non-primary attachment promotes it.

        The resolver stores the raw claimed ``is_primary`` per attachment; the
        displayed primary is a read-time selection.
        """
        # Upload two images — neither claims primary; oldest displays as primary.
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )
        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="backglass", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )
        _resolve_media(machine_model)
        assert EntityMedia.objects.get(asset=asset).is_primary is False
        assert EntityMedia.objects.get(asset=asset2).is_primary is False
        assert _displayed_primaries(machine_model) == {asset.pk}

        # Explicitly promote asset2
        _key, new_value = build_media_attachment_claim(
            machine_model, asset2.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", new_value, user=user, claim_key=key2
        )
        _resolve_media(machine_model)
        assert EntityMedia.objects.get(asset=asset2).is_primary is True
        assert _displayed_primaries(machine_model) == {asset2.pk}


# ---------------------------------------------------------------------------
# Primary enforcement
# ---------------------------------------------------------------------------


class TestPrimaryAutoPromotion:
    """The resolver stores raw claimed ``is_primary``; when no attachment in a
    (entity, category) group claims primary, the read-time selector
    auto-promotes the oldest (first uploaded)."""

    def test_single_upload_becomes_primary(self, machine_model, asset, user):
        key, val = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=False
        )
        _assert_claim(machine_model, "media_attachment", val, user=user, claim_key=key)
        _resolve_media(machine_model)

        em = EntityMedia.objects.get()
        assert em.is_primary is False  # raw claim preserved
        assert _displayed_primaries(machine_model) == {asset.pk}  # auto-promoted

    def test_first_uploaded_stays_primary(self, machine_model, asset, asset2, user):
        """Two uploads without explicit primary — oldest displays as primary."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="backglass", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )

        _resolve_media(machine_model)

        # Both store their raw (False) claim; oldest is the displayed primary.
        assert EntityMedia.objects.get(asset=asset).is_primary is False
        assert EntityMedia.objects.get(asset=asset2).is_primary is False
        assert _displayed_primaries(machine_model) == {asset.pk}

    def test_explicit_primary_not_overridden(self, machine_model, asset, asset2, user):
        """An explicit is_primary claim is stored and wins the display."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )

        _resolve_media(machine_model)

        assert EntityMedia.objects.get(asset=asset).is_primary is False
        assert EntityMedia.objects.get(asset=asset2).is_primary is True
        assert _displayed_primaries(machine_model) == {asset2.pk}

    def test_different_categories_each_get_primary(
        self, machine_model, asset, asset2, user
    ):
        """Each category independently gets a displayed primary."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="playfield", is_primary=False
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )

        _resolve_media(machine_model)

        assert _displayed_primaries(machine_model) == {asset.pk, asset2.pk}


class TestPrimaryReadTimeSelection:
    """When several attachments in one category each claim primary (the
    multi-source contention case), the resolver stores all of them raw and the
    read-time selector picks the earliest-uploaded. Claim priority and recency
    do not affect the displayed primary — only ``asset_id`` does."""

    def test_contending_primaries_oldest_wins(self, machine_model, asset, asset2, user):
        """Two claims both setting primary — both stored; oldest displays."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )

        _resolve_media(machine_model)

        assert EntityMedia.objects.get(asset=asset).is_primary is True
        assert EntityMedia.objects.get(asset=asset2).is_primary is True
        assert _displayed_primaries(machine_model) == {asset.pk}  # oldest

    def test_priority_does_not_affect_display(
        self, machine_model, asset, asset2, source, high_source
    ):
        """A higher-priority contending primary does not win the display —
        oldest still does (priority is not denormalized onto EntityMedia)."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val1, source=source, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            val2,
            source=high_source,
            claim_key=key2,
        )

        _resolve_media(machine_model)

        assert _displayed_primaries(machine_model) == {asset.pk}  # oldest, not priority

    def test_different_categories_independent(self, machine_model, asset, asset2, user):
        """Primary in different categories don't interfere."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category="playfield", is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )

        _resolve_media(machine_model)

        assert EntityMedia.objects.get(asset=asset).is_primary is True
        assert EntityMedia.objects.get(asset=asset2).is_primary is True
        assert _displayed_primaries(machine_model) == {asset.pk, asset2.pk}

    def test_null_category_is_its_own_group(self, machine_model, asset, asset2, user):
        """Null-category primaries select within their own group."""
        key1, val1 = build_media_attachment_claim(
            machine_model, asset.pk, category=None, is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val1, user=user, claim_key=key1
        )

        key2, val2 = build_media_attachment_claim(
            machine_model, asset2.pk, category=None, is_primary=True
        )
        _assert_claim(
            machine_model, "media_attachment", val2, user=user, claim_key=key2
        )

        _resolve_media(machine_model)

        assert _displayed_primaries(machine_model) == {asset.pk}  # oldest


# ---------------------------------------------------------------------------
# Interactive resolve (resolve_after_mutation) integration
# ---------------------------------------------------------------------------


class TestInteractiveResolveIntegration:
    def test_resolve_materializes_media(self, machine_model, asset, source):
        """The interactive resolve path includes media resolution."""
        from apps.provenance.resolution import resolve_after_mutation

        # Need a name claim so the resolver can save
        _assert_claim(machine_model, "name", "Test Machine", source=source)

        key, val = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass", is_primary=True
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            val,
            source=source,
            claim_key=key,
        )

        resolve_after_mutation(machine_model)

        assert EntityMedia.objects.filter(
            asset=asset, object_id=machine_model.pk
        ).exists()

    def test_retraction_via_resolve(self, machine_model, asset, source):
        """Retracting a media claim through resolve deletes EntityMedia."""
        from apps.provenance.resolution import resolve_after_mutation

        _assert_claim(machine_model, "name", "Test Machine", source=source)

        key, val = build_media_attachment_claim(
            machine_model, asset.pk, category="backglass"
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            val,
            source=source,
            claim_key=key,
        )
        resolve_after_mutation(machine_model)
        assert EntityMedia.objects.count() == 1

        # Retract
        _key, retract_val = build_media_attachment_claim(
            machine_model, asset.pk, exists=False
        )
        _assert_claim(
            machine_model,
            "media_attachment",
            retract_val,
            source=source,
            claim_key=key,
        )
        resolve_after_mutation(machine_model)
        assert EntityMedia.objects.count() == 0


# ---------------------------------------------------------------------------
# Validation in resolver
# ---------------------------------------------------------------------------


class TestResolverValidation:
    def test_invalid_category_skipped(self, machine_model, asset, source):
        """Claim with bad category doesn't materialize (belt-and-suspenders)."""
        # Bypass the helper to inject a bad category directly
        from apps.provenance.models import make_claim_key

        claim_key = make_claim_key("media_attachment", media_asset=asset.pk)
        value = {
            "media_asset": asset.pk,
            "category": "nonexistent",
            "is_primary": False,
            "exists": True,
        }
        _assert_claim(
            machine_model,
            "media_attachment",
            value,
            source=source,
            claim_key=claim_key,
        )

        _resolve_media(machine_model)
        assert EntityMedia.objects.count() == 0

    def test_nonexistent_asset_skipped(self, machine_model, source):
        """Claim referencing deleted asset doesn't materialize."""
        from apps.provenance.models import make_claim_key

        fake_pk = 99999
        claim_key = make_claim_key("media_attachment", media_asset=fake_pk)
        value = {
            "media_asset": fake_pk,
            "category": "backglass",
            "is_primary": False,
            "exists": True,
        }
        _assert_claim(
            machine_model,
            "media_attachment",
            value,
            source=source,
            claim_key=claim_key,
        )

        _resolve_media(machine_model)
        assert EntityMedia.objects.count() == 0

    def test_non_media_supported_entity_rejected(self, db, asset, source):
        """Writing a ``media_attachment`` claim on a non-MediaSupportedModel entity
        is rejected at the write path, not silently ignored at resolve time."""
        from django.core.exceptions import ValidationError

        from apps.catalog.models import Theme
        from apps.provenance.models import make_claim_key

        theme = Theme.objects.create(name="Test Theme", slug="test-theme")
        claim_key = make_claim_key("media_attachment", media_asset=asset.pk)
        value = {
            "media_asset": asset.pk,
            "category": None,
            "is_primary": False,
            "exists": True,
        }
        with pytest.raises(ValidationError, match="media_attachment"):
            _assert_claim(
                theme,
                "media_attachment",
                value,
                source=source,
                claim_key=claim_key,
            )
