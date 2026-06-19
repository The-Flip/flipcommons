"""Tests for shared API schema ownership boundaries.

Shared wire shapes should be *defined* in the app that owns the domain
concept, not in `catalog.api.schemas`. Catalog may still import and compose
them (e.g. `ClaimPatchSchema.citation: CitationReferenceInputSchema | None`), so we
check definition site via `__module__` rather than re-export presence.
"""

from apps.catalog.api import schemas as catalog_schemas
from apps.media import schemas as media_schemas
from apps.provenance import schemas as provenance_schemas
from config.api import api


class TestSharedSchemaOwnership:
    def test_provenance_owned_shapes_are_defined_in_provenance(self):
        for name in (
            "CitationReferenceInputSchema",
            "AttributionSchema",
            "CitationLinkSchema",
            "InlineCitationSchema",
            "RichTextSchema",
            "ChangeSetInputSchema",
            "ChangeSetBaseSchema",
        ):
            cls = getattr(provenance_schemas, name)
            assert cls.__module__ == "apps.provenance.schemas", (
                f"{name} should be defined in apps.provenance.schemas, "
                f"got {cls.__module__}"
            )

    def test_create_schema_is_defined_in_engine(self):
        # ``EntityCreateInputSchema`` adds ``name`` + ``slug`` to
        # ``ChangeSetInputSchema`` — a generic create shape, so it lives in the
        # domain-neutral engine (re-exported by ``catalog.api.schemas``). Pin
        # against a future move into provenance, which would force provenance to
        # import the create vocabulary.
        cls = catalog_schemas.EntityCreateInputSchema
        assert cls.__module__ == "apps.catalog.engine.schemas"

    def test_media_owned_shapes_are_defined_in_media(self):
        for name in ("MediaRenditionsSchema", "UploadedMediaSchema"):
            cls = getattr(media_schemas, name)
            assert cls.__module__ == "apps.media.schemas", (
                f"{name} should be defined in apps.media.schemas, got {cls.__module__}"
            )

    def test_openapi_changeset_input_consolidation(self):
        """Pin the dedup structurally: any component whose property set is
        exactly ``{note, citation}`` must be ``ChangeSetInputSchema``, and
        any whose set is exactly ``{name, slug, note, citation}`` must be
        ``CreateSchema``. A name-blocklist would silently rot the moment
        someone added e.g. ``FranchiseDeleteSchema``; the property-set
        check catches the fork regardless of name.
        """
        components = api.get_openapi_schema()["components"]["schemas"]

        delete_input_shape = frozenset({"note", "citation"})
        create_input_shape = frozenset({"name", "slug", "note", "citation"})

        delete_matches = {
            name
            for name, comp in components.items()
            if frozenset(comp.get("properties", {})) == delete_input_shape
        }
        assert delete_matches == {"ChangeSetInputSchema"}, (
            "Expected only ChangeSetInputSchema to have shape {note, citation}; "
            f"found {sorted(delete_matches)}"
        )

        # Schemas with ``additionalProperties: false`` are intentionally
        # tightening the base (e.g. ``LocationChildCreateSchema`` with
        # ``extra='forbid'`` to surface client-supplied ``divisions`` /
        # ``location_type`` as 422s rather than silently ignoring them).
        # Allow those — the test's purpose is to catch silent forks of
        # the shared shape, not to forbid deliberate hardening.
        create_matches = {
            name
            for name, comp in components.items()
            if frozenset(comp.get("properties", {})) == create_input_shape
            and comp.get("additionalProperties") is not False
        }
        assert create_matches == {"EntityCreateInputSchema"}, (
            "Expected only EntityCreateInputSchema to have shape "
            "{name, slug, note, citation}; "
            f"found {sorted(create_matches)}"
        )

    def test_catalog_schemas_does_not_redefine_shared_shapes(self):
        # Catalog may import and compose these, but must not define them.
        shared_names = (
            "CitationReferenceInputSchema",
            "AttributionSchema",
            "CitationLinkSchema",
            "InlineCitationSchema",
            "RichTextSchema",
            "ChangeSetInputSchema",
            "ChangeSetBaseSchema",
            "MediaRenditionsSchema",
            "UploadedMediaSchema",
        )
        for name in shared_names:
            cls = getattr(catalog_schemas, name, None)
            if cls is None:
                continue
            assert cls.__module__ != "apps.catalog.api.schemas", (
                f"{name} is defined in catalog but should live in its owning app"
            )
