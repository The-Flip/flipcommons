"""Smoke test for the export_catalog_meta management command."""

from __future__ import annotations

import re

import pytest
from django.core.management import call_command

from apps.catalog.management.commands.export_catalog_meta import (
    forward_linkable_relationships,
)
from apps.catalog.models import MachineModel


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

    def _model_relationships_block(self, output: str) -> str:
        """Extract the `relationships: { ... }` text for the `model` entity."""
        match = re.search(
            r"'model': \{.*?relationships: \{(.*?)\n\t\t\},",
            output,
            re.DOTALL,
        )
        assert match, "model relationships block not found in output"
        return match.group(1)

    def test_relationships_parity_with_meta(self, tmp_path, settings):
        """The emitted MachineModel block is the full _meta-derived map, exactly.

        Spot-check tests verify presence of a few fields; this pins the whole
        set, so the exporter can't silently drop a field (system, reward_types,
        …) or hardcode a subset.
        """
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        block = self._model_relationships_block(output)
        emitted = {
            name: (target_type, many == "true")
            for name, target_type, many in re.findall(
                r"(\w+): \{ target_type: '([\w-]+)', many: (true|false) \}", block
            )
        }
        expected = {
            name: (rel.target_type, rel.many)
            for name, rel in forward_linkable_relationships(MachineModel).items()
        }
        assert emitted == expected

    def test_relationships_forward_fk_only(self, tmp_path, settings):
        """relationships holds forward FK/M2M, never reverse accessors."""
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        block = self._model_relationships_block(output)
        # Forward FK present.
        assert "title:" in block
        assert "corporate_entity:" in block
        assert "variant_of:" in block
        # Reverse accessors of model's self-FKs (auto-created) must be excluded;
        # if the `not f.auto_created` filter regressed these would leak in.
        assert "variants:" not in block
        assert "conversions:" not in block
        assert "remakes:" not in block

    def test_relationships_target_types_match_entity_types(self, tmp_path, settings):
        """Every emitted target_type resolves to a CATALOG_META entry."""
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        entity_keys = set(re.findall(r"\n\t'([\w-]+)': \{\n\t\tentity_type:", output))
        target_types = set(re.findall(r"target_type: '([\w-]+)'", output))
        assert target_types, "no relationships emitted"
        assert target_types <= entity_keys, (
            f"target_types with no entry: {target_types - entity_keys}"
        )

    def test_relationships_many_cardinality(self, tmp_path, settings):
        """`many` mirrors the field's M2M cardinality; self-FKs round-trip."""
        settings.BASE_DIR = tmp_path / "backend"
        (tmp_path / "frontend" / "src" / "lib" / "models").mkdir(parents=True)
        call_command("export_catalog_meta")

        output = (
            tmp_path / "frontend" / "src" / "lib" / "models" / "model-meta.ts"
        ).read_text()
        block = self._model_relationships_block(output)
        # FK -> many: false
        assert "title: { target_type: 'title', many: false }" in block
        assert (
            "corporate_entity: { target_type: 'corporate-entity', many: false }"
            in block
        )
        # M2M -> many: true
        assert "themes: { target_type: 'theme', many: true }" in block
        assert (
            "gameplay_features: { target_type: 'gameplay-feature', many: true }"
            in block
        )
        # Self-referential FK round-trips as a forward FK.
        assert "variant_of: { target_type: 'model', many: false }" in block

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
