"""Domain API schemas used by multiple catalog routers.

The cross-cutting wire bases (``EntityRef``, the detail bases, the generic claim
patch bases) live in ``catalog.engine.schemas`` and are re-exported here so the
domain routers keep their ``from .schemas import …`` import sites. This module
owns only the entity-specific variants.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from ninja import Schema
from pydantic import Field

from apps.provenance.schemas import ChangeSetInputSchema, InlineCitationsInputSchema

from ..engine.entity_api.delete.schemas import (
    AlreadyDeletedSchema,
    BlockingReferrerSchema,
    DeletePreviewBaseSchema,
    DeleteResponseSchema,
    SoftDeleteBlockedSchema,
)
from ..engine.schemas import (
    ClaimPatchSchema,
    DescribedDetailSchema,
    EntityCreateInputSchema,
    EntityDetailSchema,
    EntityRef,
    FacetOptionSchema,
    HierarchyClaimPatchSchema,
    LastModifiedDetailSchema,
    LinkableDetailSchema,
    OwnMediaSchema,
    YearBoundsSchema,
)

__all__ = [
    "AlreadyDeletedSchema",
    "BlockingReferrerSchema",
    "ClaimPatchSchema",
    "DeletePreviewBaseSchema",
    "DeleteResponseSchema",
    "DescribedDetailSchema",
    "EntityCreateInputSchema",
    "EntityDetailSchema",
    "EntityRef",
    "FacetOptionSchema",
    "HierarchyClaimPatchSchema",
    "LastModifiedDetailSchema",
    "LinkableDetailSchema",
    "OwnMediaSchema",
    "SoftDeleteBlockedSchema",
    "YearBoundsSchema",
]


class CorporateEntityClaimPatchSchema(ChangeSetInputSchema, InlineCitationsInputSchema):
    """Patch body for manufacturer/operator/etc. — aliases, but no parents
    (corporate entities are flat, not hierarchical)."""

    # See ClaimPatchSchema.fields — polymorphic per claim field, validated downstream.
    fields: dict[str, Any] = {}
    aliases: list[str] | None = None


class GameplayFeatureInputSchema(Schema):
    """Nested entry in :class:`ModelClaimPatchSchema.gameplay_features` —
    standalone because each entry carries a ``count`` alongside the slug.
    """

    slug: str
    count: int | None = None


class CreditInputSchema(Schema):
    """Nested entry in :class:`ModelClaimPatchSchema.credits` — standalone
    because each entry pairs a person slug with a role.
    """

    person_slug: str
    role: str


# Wire unions for the relationship editor. Literal (not str) so the generated
# schema.d.ts carries them as unions the frontend derives from; locked against
# the model TextChoices by a snapshot test in test_api_claims_model_relationships.
# Plain assignments (not `type` statements): a PEP 695 alias would become a
# named OpenAPI component and trip the Schema/Ref suffix discipline — these
# should inline anonymously into the field schemas.
RelationshipTypeLiteral = Literal["conversion", "conversion_kit", "copy", "retheme"]
LicenseStatusLiteral = Literal["licensed", "unlicensed", "unknown"]

# Runtime bridges from the stored CharField values (plain ``str`` to mypy) to
# the wire Literals, for serializers that build Literal-typed schema fields
# from ORM rows. KeyError on an out-of-vocab value — impossible while the DB
# CHECK constraints hold.
RELATIONSHIP_TYPE_TO_LITERAL: dict[str, RelationshipTypeLiteral] = {
    v: v for v in get_args(RelationshipTypeLiteral)
}
LICENSE_STATUS_TO_LITERAL: dict[str, LicenseStatusLiteral] = {
    v: v for v in get_args(LicenseStatusLiteral)
}


class ModelRelationshipInputSchema(Schema):
    """Nested entry in :class:`ModelClaimPatchSchema.relationships` — one typed
    edge. Exactly one of ``target_slug`` / ``target_label`` must be set (the
    target XOR); the planner rejects both-or-neither with a row error.
    """

    relationship_type: RelationshipTypeLiteral
    license_status: LicenseStatusLiteral = "unknown"
    target_slug: str = Field(
        "", description="Public id of the target machine, when seeded."
    )
    target_label: str = Field(
        "",
        description=(
            "Plain-text target descriptor when the target isn't seeded "
            '(e.g. "several Gottlieb EM models"). No markdown, no wikilinks.'
        ),
    )


class ModelClaimPatchSchema(ChangeSetInputSchema, InlineCitationsInputSchema):
    """Patch body for Model — the widest entity, with several list payloads
    on top of the generic ``fields`` bag.
    """

    # See ClaimPatchSchema.fields — polymorphic per claim field, validated downstream.
    fields: dict[str, Any] = {}
    themes: list[str] | None = None
    tags: list[str] | None = None
    reward_types: list[str] | None = None
    gameplay_features: list[GameplayFeatureInputSchema] | None = None
    credits: list[CreditInputSchema] | None = None
    abbreviations: list[str] | None = None
    relationships: list[ModelRelationshipInputSchema] | None = None


class TitleClaimPatchSchema(ChangeSetInputSchema, InlineCitationsInputSchema):
    """Patch body for Title — narrow because most attributes live on Model
    (see [docs/SingleModelTitles.md] for the asymmetric split).
    """

    # See ClaimPatchSchema.fields — polymorphic per claim field, validated downstream.
    fields: dict[str, Any] = {}
    abbreviations: list[str] | None = None


class PersonSoftDeleteBlockedSchema(Schema):
    """422 response from Person delete when active credits block.

    Separate from :class:`SoftDeleteBlockedSchema` because Credits are
    referential, not lifecycle-owned children: the count is computed by
    joining Credit to its active parent Model/Series rather than walking an
    FK back from the child (see ``_active_credit_count`` in people.py).
    ``blocked_by`` is required for the same union-dispatch reason as
    :class:`SoftDeleteBlockedSchema`.
    """

    detail: str
    blocked_by: list[BlockingReferrerSchema]
    active_credit_count: int = 0


class ModelDeletePreviewSchema(DeletePreviewBaseSchema):
    parent: EntityRef


class PersonDeletePreviewSchema(DeletePreviewBaseSchema):
    # Count of Credits whose parent Model or Series is still active.
    # When non-zero the UI refuses the delete (see people.py:delete_person);
    # Credit rows are owned children of Model/Series so the generic
    # soft-delete walker doesn't see them.
    active_credit_count: int


class TitleDeletePreviewSchema(DeletePreviewBaseSchema):
    # Cascade impact, NOT a blocker — Title delete cascades into its active
    # MachineModels (see titles.py:delete_title). Surfaced so the UI can
    # warn "this will also delete N machines."
    active_model_count: int


class EditOptionSchema(Schema):
    slug: str
    label: str


class ModelEditOptionsSchema(Schema):
    tags: list[EditOptionSchema]
    reward_types: list[EditOptionSchema]
    technology_generations: list[EditOptionSchema]
    technology_subgenerations: list[EditOptionSchema]
    display_types: list[EditOptionSchema]
    display_subtypes: list[EditOptionSchema]
    cabinets: list[EditOptionSchema]
    game_formats: list[EditOptionSchema]
    production_statuses: list[EditOptionSchema]
    systems: list[EditOptionSchema]
    credit_roles: list[EditOptionSchema]


class TitleModelVariantSchema(Schema):
    """A variant of a machine model, shown nested under its parent."""

    name: str
    public_id: str
    year: int | None = None
    thumbnail_url: str | None = None


class TitleModelSchema(Schema):
    """A machine model shown in a list context (title detail, theme detail, etc.)."""

    name: str
    public_id: str
    year: int | None = None
    manufacturer: EntityRef | None = None
    technology_generation_name: str | None = None
    thumbnail_url: str | None = None
    variants: list[TitleModelVariantSchema] = []


class RelatedTitleSchema(Schema):
    """A title shown in a related-entity list context (manufacturer, system, etc.)."""

    name: str
    public_id: str
    year: int | None = None
    manufacturer_name: str | None = None
    thumbnail_url: str | None = None


class TitleRef(EntityRef):
    abbreviations: list[str] = []
    model_count: int = 0
    manufacturer_name: str | None = None  # display-only, no paired slug
    year: int | None = None
    thumbnail_url: str | None = None


class GameplayFeatureRef(EntityRef):
    count: int | None = None


class CreditSchema(Schema):
    person: EntityRef
    role: str
    role_display: str
    role_sort_order: int


class CorporateEntityLocationAncestorRef(Schema):
    """An ancestor in a location's breadcrumb. ``public_id`` is the location's
    full path."""

    # Slimmer than ``CorporateEntityLocationSchema`` — ancestors render as a
    # breadcrumb, so ``location_type`` is omitted.
    display_name: str = Field(description="The ancestor location's display name.")
    public_id: str = Field(description="The ancestor location's full path.")


class CorporateEntityLocationSchema(Schema):
    """A corporate entity's location plus its ancestor chain. ``public_id`` is the
    location's full path."""

    public_id: str = Field(description="The location's full path.")
    location_type: str = Field(
        description="The kind of location (e.g. country, region, city)."
    )
    display_name: str = Field(description="The location's display name.")
    ancestors: list[CorporateEntityLocationAncestorRef] = Field(
        [], description="The location's ancestor chain, as a breadcrumb."
    )
