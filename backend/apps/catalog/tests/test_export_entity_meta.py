"""Smoke test for the export_entity_meta management command."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.catalog.management.commands.export_entity_meta import (
    forward_linkable_relationships,
)
from apps.catalog.models import MachineModel


@pytest.fixture
def output(tmp_path: Path, settings) -> str:
    """Run the command into a temp tree and return the generated TS source.

    The command mkdirs its own output dir, so no pre-creation is needed. This is
    the raw (un-prettier'd) emitter output, so assertions can rely on the tab
    indentation the generator writes.
    """
    settings.BASE_DIR = tmp_path / "backend"
    call_command("export_entity_meta")
    return (
        tmp_path / "frontend" / "src" / "lib" / "entities" / "entity-meta.ts"
    ).read_text()


def _model_relationships_block(output: str) -> str:
    """Extract the `relationships: { ... }` text for the `model` entity."""
    match = re.search(
        r"'model': \{.*?relationships: \{(.*?)\n\t\t\},",
        output,
        re.DOTALL,
    )
    assert match, "model relationships block not found in output"
    return match.group(1)


@pytest.mark.django_db
class TestExportEntityMeta:
    def test_output_contains_expected_exports(self, output: str) -> None:
        assert "export const ENTITY_META" in output
        assert "export type EntityKey" in output
        assert "export type CatalogEntityKey" in output
        assert "export type MediaSupportedEntityKey" in output
        assert "export const CATALOG_ENTITY_KEYS" in output
        assert "export interface EntityMetadata" in output
        assert "export interface EntityRelationship" in output
        # Media categories are folded into each entry — there is no standalone const.
        assert "export const MEDIA_CATEGORIES" not in output

    def test_entities_emitted_in_sorted_order(self, output: str) -> None:
        # Determinism is the exporter's own responsibility (stable codegen diffs):
        # it sorts by entity_type regardless of the registry's enumeration order.
        keys = re.findall(r"\n\t'([\w-]+)': \{\n\t\tentity_type:", output)
        assert len(keys) > 1, "expected multiple ENTITY_META entries"
        assert keys == sorted(keys)

    def test_known_models_present(self, output: str) -> None:
        for name in ("model", "title", "manufacturer", "person", "theme"):
            assert f"'{name}': {{" in output, f"{name} missing from ENTITY_META"
            assert f"entity_type: '{name}'" in output

    def test_media_categories_folded_into_entries(self, output: str) -> None:
        # Media-bearing entities carry their category list inline.
        assert (
            "media_categories: ['backglass', 'playfield', 'cabinet', 'other']" in output
        )
        assert "media_categories: ['logo', 'other']" in output
        # Non-media entities carry an empty list (required field, not optional).
        assert "media_categories: []" in output

    def test_media_supported_union_is_the_media_subset(self, output: str) -> None:
        match = re.search(r"export type MediaSupportedEntityKey = ([^;]+);", output)
        assert match, "MediaSupportedEntityKey union not found"
        keys = set(re.findall(r"'([\w-]+)'", match.group(1)))
        assert keys == {"gameplay-feature", "manufacturer", "model", "person"}

    def test_catalog_entity_keys_runtime_array(self, output: str) -> None:
        match = re.search(
            r"export const CATALOG_ENTITY_KEYS = \[(.*?)\] as const;",
            output,
            re.DOTALL,
        )
        assert match, "CATALOG_ENTITY_KEYS array not found"
        keys = set(re.findall(r"'([\w-]+)'", match.group(1)))
        # All current entities are catalog, so the runtime array spans them.
        assert {"model", "title", "manufacturer", "person", "theme"} <= keys

    def test_key_types_single_enumeration(self, output: str) -> None:
        # CatalogEntityKey derives from the array; EntityKey composes from
        # CatalogEntityKey — so no key is enumerated as a literal more than once.
        assert (
            "export type CatalogEntityKey = (typeof CATALOG_ENTITY_KEYS)[number];"
            in output
        )
        # Today every entity is catalog, so EntityKey is exactly CatalogEntityKey
        # (non-catalog keys would append as ` | 'user' | …`).
        assert "export type EntityKey = CatalogEntityKey;" in output

    def test_relationships_parity_with_meta(self, output: str) -> None:
        """The emitted MachineModel block is the full _meta-derived map, exactly.

        Spot-check tests verify presence of a few fields; this pins the whole
        set, so the exporter can't silently drop a field (system, reward_types,
        …) or hardcode a subset.
        """
        block = _model_relationships_block(output)
        emitted = {
            name: (target_type, many == "true")
            for name, target_type, many in re.findall(
                r"(\w+): \{ entity_target_type: '([\w-]+)', many: (true|false) \}",
                block,
            )
        }
        expected = {
            name: (rel.target_type, rel.many)
            for name, rel in forward_linkable_relationships(MachineModel).items()
        }
        assert emitted == expected

    def test_relationships_forward_fk_only(self, output: str) -> None:
        """relationships holds forward FK/M2M, never reverse accessors."""
        block = _model_relationships_block(output)
        # Forward FK present.
        assert "title:" in block
        assert "corporate_entity:" in block
        assert "variant_of:" in block
        # Reverse accessors of model's self-FKs (auto-created) must be excluded;
        # if the `not f.auto_created` filter regressed these would leak in.
        assert "variants:" not in block
        assert "conversions:" not in block
        assert "remakes:" not in block

    def test_relationships_target_types_match_entity_types(self, output: str) -> None:
        """Every emitted target_type resolves to an ENTITY_META entry."""
        entity_keys = set(re.findall(r"\n\t'([\w-]+)': \{\n\t\tentity_type:", output))
        target_types = set(re.findall(r"entity_target_type: '([\w-]+)'", output))
        assert target_types, "no relationships emitted"
        assert target_types <= entity_keys, (
            f"target_types with no entry: {target_types - entity_keys}"
        )

    def test_relationships_many_cardinality(self, output: str) -> None:
        """`many` mirrors the field's M2M cardinality; self-FKs round-trip."""
        block = _model_relationships_block(output)
        # FK -> many: false
        assert "title: { entity_target_type: 'title', many: false }" in block
        assert (
            "corporate_entity: { entity_target_type: 'corporate-entity', many: false }"
            in block
        )
        # M2M -> many: true
        assert "themes: { entity_target_type: 'theme', many: true }" in block
        assert (
            "gameplay_features: { entity_target_type: 'gameplay-feature', many: true }"
            in block
        )
        # Self-referential FK round-trips as a forward FK.
        assert "variant_of: { entity_target_type: 'model', many: false }" in block

    def test_output_is_valid_typescript_shape(self, output: str) -> None:
        """Generated file ends with a newline and has no raw Python artifacts."""
        assert output.endswith("\n")
        assert "None" not in output
        assert "True" not in output
        assert "False" not in output
        # The literal is pinned and shape-validated.
        assert "as const satisfies Record<EntityKey, EntityMetadata>" in output
