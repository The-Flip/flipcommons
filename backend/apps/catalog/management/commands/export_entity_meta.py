"""Generate frontend/src/lib/entities/entity-meta.ts from linkable models.

Iterates every concrete ``LinkableModel`` (cross-app, via
``core.entity_types.all_linkable_models``) to produce a TypeScript file with:

- ENTITY_META: per-entity record keyed by entity_type, exposing entity_type,
  entity_type_plural, label, label_plural, a ``relationships`` map of forward
  FK / M2M fields to their ``{entity_target_type, many}`` shape, and ``media_categories``
  (``[]`` for entities without media). Consumed by polymorphic frontend code
  that needs a typed registry of entities (e.g. the global changes feed, the
  JSON-LD assembler).
- EntityKey / CatalogEntityKey / MediaSupportedEntityKey: explicit literal unions
  (the full set, the catalog subset, and the media-bearing subset).
- CATALOG_ENTITY_KEYS: a runtime array of the catalog subset, for code that must
  iterate or membership-test catalog entities at runtime (a type cannot do that).

The registry is registry-driven: a new linkable entity (e.g. a future SSR
``User``) joins automatically by subclassing ``LinkableModel``. Catalog-ness is
computed via ``issubclass(CatalogModel)`` purely to emit the catalog subset.

Run via ``make codegen`` or directly::

    python manage.py export_entity_meta
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Model

from apps.catalog.models.base import CatalogModel
from apps.core.entity_types import all_linkable_models
from apps.core.models import LinkableModel


class Relationship(NamedTuple):
    target_type: str
    many: bool


def forward_linkable_relationships(cls: type[Model]) -> dict[str, Relationship]:
    """Forward FK / M2M fields of ``cls`` whose target is a ``LinkableModel``.

    Reverse accessors (``auto_created``) are excluded — only relations the
    entity declares itself, which are the ones its detail response serializes
    as refs. Targets must be ``LinkableModel`` to have a canonical URL the
    frontend can turn into a JSON-LD ``@id``.
    """
    relationships: dict[str, Relationship] = {}
    for f in cls._meta.get_fields():
        target = f.related_model
        if (
            f.is_relation
            and not f.auto_created
            and isinstance(target, type)
            and issubclass(target, LinkableModel)
        ):
            relationships[f.name] = Relationship(
                target.entity_type, bool(f.many_to_many)
            )
    return relationships


class EntityEntry(NamedTuple):
    entity_type: str
    entity_type_plural: str
    label: str
    label_plural: str
    relationships: dict[str, Relationship]
    media_categories: list[str]
    is_catalog: bool


def _union(keys: list[str]) -> str:
    """A TypeScript literal union of single-quoted keys, ``never`` if empty."""
    return " | ".join(f"'{k}'" for k in keys) if keys else "never"


class Command(BaseCommand):
    help = "Generate frontend/src/lib/entities/entity-meta.ts from linkable models."

    def handle(
        self,
        **options: Any,  # noqa: ANN401 - argparse-driven Django command kwargs
    ) -> None:
        entries = [
            EntityEntry(
                entity_type=cls.entity_type,
                entity_type_plural=cls.entity_type_plural,
                label=str(cls._meta.verbose_name).title(),
                label_plural=str(cls._meta.verbose_name_plural).title(),
                relationships=forward_linkable_relationships(cls),
                media_categories=list(getattr(cls, "MEDIA_CATEGORIES", [])),
                is_catalog=issubclass(cls, CatalogModel),
            )
            for cls in all_linkable_models()
        ]
        # The exporter owns output determinism: sort by entity_type so ENTITY_META
        # and the key unions emit in a stable order (clean codegen diffs),
        # independent of the registry's enumeration order.
        entries.sort(key=lambda e: e.entity_type)

        # Every emitted entity_target_type must resolve to an ENTITY_META entry, or the
        # frontend assembler reads relationships[field] as undefined and crashes
        # at render. all_linkable_models() covers every concrete LinkableModel,
        # so this holds for any relationship whose target is itself linkable.
        keys = {e.entity_type for e in entries}
        for entry in entries:
            for field, rel in entry.relationships.items():
                if rel.target_type not in keys:
                    raise CommandError(
                        f"{entry.entity_type}.{field} targets "
                        f"'{rel.target_type}', which has no ENTITY_META entry."
                    )

        catalog_keys = [e.entity_type for e in entries if e.is_catalog]
        non_catalog_keys = [e.entity_type for e in entries if not e.is_catalog]
        media_keys = [e.entity_type for e in entries if e.media_categories]

        # EntityKey is composed from CatalogEntityKey plus any non-catalog keys, so
        # catalog ⊆ entity holds by construction — each key is enumerated once (in
        # the catalog array or inline here), and the array needs no `satisfies`
        # cross-check against EntityKey (which would also be circular).
        entity_key_def = "CatalogEntityKey"
        if non_catalog_keys:
            tail = " | ".join(f"'{k}'" for k in non_catalog_keys)
            entity_key_def = f"CatalogEntityKey | {tail}"

        lines = [
            "// Generated by: python manage.py export_entity_meta",
            "// Do not edit manually.",
            "",
            "/**",
            " * Runtime array of the catalog entity keys — the subset of",
            " * {@link ENTITY_META} whose models are `CatalogModel`s. Use this (not",
            " * `Object.keys(ENTITY_META)` / `k in ENTITY_META`) wherever catalog-only",
            " * code iterates or membership-tests keys at runtime: a type narrows but",
            " * cannot exclude a non-catalog key from the actual object.",
            " *",
            " * The single enumeration of the catalog vocabulary: {@link CatalogEntityKey}",
            " * derives from this array and {@link EntityKey} is composed from that.",
            " */",
            "export const CATALOG_ENTITY_KEYS = [",
            *[f"\t'{key}'," for key in catalog_keys],
            "] as const;",
            "",
            "/** Union of catalog entity `entity_type`s — the `CatalogModel` subset"
            " of {@link EntityKey}. */",
            "export type CatalogEntityKey = (typeof CATALOG_ENTITY_KEYS)[number];",
            "",
            "/** Union of every entity `entity_type` — the catalog keys plus any"
            " non-catalog linkable entities (e.g. a future SSR `user`). */",
            f"export type EntityKey = {entity_key_def};",
            "",
            "/** Identity type that fails to compile unless `S` is a subset of `U`;"
            " keeps a generated key subset within {@link EntityKey}. */",
            "type SubsetOf<S extends U, U> = S;",
            "",
            "/** Union of entity `entity_type`s that support media uploads. */",
            f"export type MediaSupportedEntityKey = SubsetOf<{_union(media_keys)}, EntityKey>;",
            "",
            "/**",
            " * A forward FK / M2M relationship an entity declares to another entity.",
            " */",
            "export interface EntityRelationship {",
            "\t/** The related entity's `entity_type` */",
            "\tentity_target_type: EntityKey;",
            "\t/** true for M2M, false for FK */",
            "\tmany: boolean;",
            "}",
            "",
            "/** Per-entity metadata: the shape of each {@link ENTITY_META} value. */",
            "export interface EntityMetadata {",
            "\tentity_type: EntityKey;",
            "\tentity_type_plural: string;",
            "\tlabel: string;",
            "\tlabel_plural: string;",
            "\trelationships: Record<string, EntityRelationship>;",
            "\t/** Allowed media-upload categories; `[]` for entities without media. */",
            "\tmedia_categories: readonly string[];",
            "}",
            "",
            "/**",
            " * Registry of entity metadata, keyed by `entity_type`. Source of truth",
            " * for the frontend's entity-type vocabulary, labels, relationship shapes",
            " * and media categories. Consumed by polymorphic code (changes feed,",
            " * JSON-LD assembler, sitemap, taxonomy pages). Generated — do not edit.",
            " */",
            "export const ENTITY_META = {",
        ]
        for entry in entries:
            lines.append(f"\t'{entry.entity_type}': {{")
            lines.append(f"\t\tentity_type: '{entry.entity_type}',")
            lines.append(f"\t\tentity_type_plural: '{entry.entity_type_plural}',")
            lines.append(f"\t\tlabel: '{entry.label}',")
            lines.append(f"\t\tlabel_plural: '{entry.label_plural}',")
            lines.append("\t\trelationships: {")
            for field in sorted(entry.relationships):
                rel = entry.relationships[field]
                many = "true" if rel.many else "false"
                lines.append(
                    f"\t\t\t{field}: {{ entity_target_type: '{rel.target_type}', "
                    f"many: {many} }},"
                )
            lines.append("\t\t},")
            cats = ", ".join(f"'{c}'" for c in entry.media_categories)
            lines.append(f"\t\tmedia_categories: [{cats}],")
            lines.append("\t},")
        lines.append("} as const satisfies Record<EntityKey, EntityMetadata>;")
        lines.append("")

        output_path = (
            Path(settings.BASE_DIR).parent / "frontend/src/lib/entities/entity-meta.ts"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines))
        self.stdout.write(self.style.SUCCESS(f"Wrote {output_path}"))
