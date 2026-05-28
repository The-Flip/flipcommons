"""Smoke test for the export_catalog_meta management command."""

from __future__ import annotations

import re

import pytest
from django.core.management import call_command


@pytest.mark.django_db
class TestExportCatalogMeta:
    def test_output_contains_catalog_meta(self, tmp_path, settings):
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        assert "export const CATALOG_META" in output
        assert "export type CatalogEntityKey" in output
        assert "export const MEDIA_CATEGORIES" in output

    def test_known_models_present(self, tmp_path, settings):
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        for name in ("model", "title", "manufacturer", "person", "theme"):
            assert f"'{name}': {{" in output, f"{name} missing from CATALOG_META"
            assert f"entity_type: '{name}'" in output

    def test_media_categories_present(self, tmp_path, settings):
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        assert "'model': [" in output
        assert "'backglass'" in output
        assert "'manufacturer': [" in output
        assert "'logo'" in output

    def test_output_is_valid_typescript_shape(self, tmp_path, settings):
        """Generated file ends with a newline and has no raw Python artifacts."""
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        assert output.endswith("\n")
        assert "None" not in output
        assert "True" not in output
        assert "False" not in output
        # Should have the as const assertions
        assert re.search(r"CATALOG_META.*as const", output, re.DOTALL)
        assert re.search(r"MEDIA_CATEGORIES.*as const", output, re.DOTALL)
