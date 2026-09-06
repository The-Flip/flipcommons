"""Tests for media storage key generation and URL building."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.media.storage import (
    build_public_url,
    build_storage_key,
    delete_from_storage,
    upload_to_storage,
)


class TestBuildStorageKey:
    """build_storage_key() derives deterministic paths from asset UUID + rendition type."""

    def test_original(self):
        asset_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        key = build_storage_key(asset_uuid, "original")
        assert key == "media/12345678-1234-5678-1234-567812345678/original"

    def test_thumb(self):
        asset_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        key = build_storage_key(asset_uuid, "thumb")
        assert key == "media/12345678-1234-5678-1234-567812345678/thumb"

    def test_display(self):
        asset_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        key = build_storage_key(asset_uuid, "display")
        assert key == "media/12345678-1234-5678-1234-567812345678/display"

    def test_invalid_rendition_type_rejected(self):
        asset_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        with pytest.raises(ValueError, match="rendition_type"):
            build_storage_key(asset_uuid, "poster")


class TestBuildPublicUrl:
    """build_public_url() concatenates base URL + storage key."""

    @override_settings(MEDIA_PUBLIC_BASE_URL="https://media.example.com/")
    def test_basic_url(self):
        url = build_public_url("media/abc/thumb")
        assert url == "https://media.example.com/media/abc/thumb"

    @override_settings(MEDIA_PUBLIC_BASE_URL="https://media.example.com")
    def test_base_url_without_trailing_slash(self):
        url = build_public_url("media/abc/thumb")
        assert url == "https://media.example.com/media/abc/thumb"

    @override_settings(MEDIA_PUBLIC_BASE_URL="/media/")
    def test_relative_base_url(self):
        url = build_public_url("media/abc/thumb")
        assert url == "/media/media/abc/thumb"


class TestUploadToStorage:
    """upload_to_storage() detects key mismatches from the storage backend."""

    def test_key_mismatch_raises_and_cleans_up(self):
        mock_storage = MagicMock()
        mock_storage.save.return_value = "media/abc/thumb_renamed"

        with (
            patch("apps.media.storage.get_media_storage", return_value=mock_storage),
            pytest.raises(RuntimeError, match="Storage key mismatch"),
        ):
            upload_to_storage("media/abc/thumb", b"data", "image/webp")

        mock_storage.delete.assert_called_once_with("media/abc/thumb_renamed")

    def test_matching_key_succeeds(self):
        mock_storage = MagicMock()
        mock_storage.save.return_value = "media/abc/thumb"

        with patch("apps.media.storage.get_media_storage", return_value=mock_storage):
            upload_to_storage("media/abc/thumb", b"data", "image/webp")

        mock_storage.delete.assert_not_called()


class TestDeleteFromStorage:
    def test_returns_the_keys_it_could_not_delete(self):
        mock_storage = MagicMock()

        def delete(key):
            if key == "media/abc/thumb":
                raise OSError("bucket unreachable")

        mock_storage.delete.side_effect = delete

        with patch("apps.media.storage.get_media_storage", return_value=mock_storage):
            leaked = delete_from_storage(
                ["media/abc/original", "media/abc/thumb", "media/abc/display"]
            )

        assert leaked == ["media/abc/thumb"]
        assert mock_storage.delete.call_count == 3
