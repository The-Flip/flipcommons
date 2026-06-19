"""Cross-cutting wire schema bases for the generic entity HTTP surface.

Domain-neutral schema bases shared across the engine's surfaces (and re-exported
by ``catalog.api.schemas`` for the domain routers, the sanctioned domain → engine
edge). Entity-specific variants (``ModelClaimPatchSchema``, the delete-preview
subclasses, …) stay domain-side in ``catalog.api.schemas``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from ninja import Schema
from pydantic import Field

from apps.media.schemas import UploadedMediaSchema
from apps.provenance.schemas import ChangeSetInputSchema, RichTextSchema

__all__ = [
    "ClaimPatchSchema",
    "DescribedDetailSchema",
    "EntityCreateInputSchema",
    "EntityDetailSchema",
    "EntityRef",
    "FacetOptionSchema",
    "HierarchyClaimPatchSchema",
    "LastModifiedDetailSchema",
    "LinkableDetailSchema",
    "OwnMediaSchema",
    "YearBoundsSchema",
]


class EntityRef(Schema):
    """A reference to an entity."""

    name: str = Field(description="The entity's human-readable display name.")
    public_id: str = Field(
        description="The entity's public identifier, usually its slug."
    )


class FacetOptionSchema(Schema):
    """One selectable facet value with its live result count."""

    # Shared by every faceted listing page (titles, manufacturers) so there is
    # exactly one OpenAPI component: two identically-named-but-separate classes
    # would collide into ``FacetOptionSchema`` + ``FacetOptionSchema2`` the moment
    # one gained a field, and the frontend's named import would bind
    # non-deterministically.
    public_id: str = Field(
        description="The facet value's identifier (the entity's slug)."
    )
    name: str = Field(description="The facet value's display name.")
    count: int = Field(description="Number of matching results with this value.")


class YearBoundsSchema(Schema):
    """Inclusive min/max for a year-range facet."""

    # Lives here (not per-entity) for the same single-component reason as
    # ``FacetOptionSchema``.
    min: Annotated[int | None, Field(description="Earliest year, inclusive.")] = None
    max: Annotated[int | None, Field(description="Latest year, inclusive.")] = None


class LinkableDetailSchema(Schema):
    """A top-level entity's display name and URL identity."""

    name: str = Field(description="The entity's human-readable display name.")
    # ``public_id`` is the model's ``LinkableModel.public_id`` — a slug for most
    # entities, a ``location_path`` for Location. Required (no default) so every
    # serializer sources it.
    public_id: str = Field(
        description="The entity's public identifier, usually its slug."
    )


class DescribedDetailSchema(Schema):
    """An entity's rich-text description."""

    description: RichTextSchema = Field(
        default=RichTextSchema(),
        description="The entity's description as rich text.",
    )


class LastModifiedDetailSchema(Schema):
    """An entity's last-modified timestamp."""

    # Sourced from ``LastUpdatedModel.last_modified`` (the ``_last_modified``
    # annotation), NOT raw ``updated_at`` — so a ``Title`` reflects edits to its
    # child Models. Drives the sitemap ``<lastmod>`` and JSON-LD ``dateModified``.
    # Required (no default) so every serializer sources it.
    last_modified: datetime = Field(
        description=(
            "When the entity was last modified. For entities with children, "
            "reflects the most recent change to any child."
        )
    )


class EntityDetailSchema(
    LinkableDetailSchema, LastModifiedDetailSchema, DescribedDetailSchema
):
    """Base for entity detail responses: name, URL identity, last-modified and
    description."""

    # Backend counterpart of the frontend's ``EntityBaseFacts``. Composes three
    # orthogonal concern mixins — linkability ("has a canonical URL"), freshness
    # ("when did this last change") and describability — mirroring the
    # ``LinkableModel`` / ``LastUpdatedModel`` / ``DescribedModel`` split on the
    # model side. Top-level entity detail responses inherit this single base.


class OwnMediaSchema(Schema):
    """An entity's own uploaded-media gallery.

    Mixed into the detail schema of every ``MediaSupportedModel``. The field is
    engine-contributed and engine-filled: the ``own_media`` decorator
    (:mod:`apps.catalog.engine.entity_api.own_media`) populates it after the
    per-entity serializer runs, gated on ``issubclass(model_cls,
    MediaSupportedModel)``, so a domain serializer never serializes its own
    gallery. ``register_entity_detail_page`` asserts at registration that a
    media model's detail schema inherits this base.
    """

    uploaded_media: list[UploadedMediaSchema] = Field(
        default=[],
        description="Media uploaded directly to this entity (its own gallery).",
    )


class EntityCreateInputSchema(ChangeSetInputSchema):
    """Base shape for entity create operations."""

    name: str
    slug: str


class ClaimPatchSchema(ChangeSetInputSchema):
    """Generic claim-patch body for entity types with no list-shaped
    payloads beyond ``fields``. Entity types that own M2M/list relations
    (parents, aliases, themes, credits, …) use per-entity subclasses instead.
    """

    # ``fields`` maps claim-field name → new value. Values are polymorphic per
    # field (str, int, bool, slug string for FK-backed claims, None) and are
    # validated downstream by ``validate_claim_value``; no fixed TypedDict.
    fields: dict[str, Any]


class HierarchyClaimPatchSchema(ChangeSetInputSchema):
    """Patch body for hierarchy-shaped taxonomies (themes, locations,
    technology generations, …) whose claims include parent links and aliases.
    """

    # See ClaimPatchSchema.fields — polymorphic per claim field, validated downstream.
    fields: dict[str, Any] = {}
    parents: list[str] | None = None
    aliases: list[str] | None = None
