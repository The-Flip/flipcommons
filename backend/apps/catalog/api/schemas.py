"""Shared API schemas used by multiple routers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from ninja import Schema
from pydantic import ConfigDict, Field

from apps.provenance.schemas import ChangeSetInputSchema, RichTextSchema


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


class CatalogDetailSchema(
    LinkableDetailSchema, LastModifiedDetailSchema, DescribedDetailSchema
):
    """Base for catalog detail responses: name, URL identity, last-modified and
    description."""

    # Backend counterpart of the frontend's ``EntityBaseFacts``. Composes three
    # orthogonal concern mixins — linkability ("has a canonical URL"), freshness
    # ("when did this last change") and describability — mirroring the
    # ``LinkableModel`` / ``LastUpdatedModel`` / ``DescribedModel`` split on the
    # model side. Top-level catalog detail responses inherit this single base.


class EntityCreateInputSchema(ChangeSetInputSchema):
    """Base shape for catalog entity create operations."""

    name: str
    slug: str


class ClaimPatchSchema(ChangeSetInputSchema):
    """Generic claim-patch body for entity types with no list-shaped
    payloads beyond ``fields``. Entity types that own M2M/list relations
    (parents, aliases, themes, credits, …) use the per-entity subclasses
    below instead.
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


class CorporateEntityClaimPatchSchema(ChangeSetInputSchema):
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


class ModelClaimPatchSchema(ChangeSetInputSchema):
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


class TitleClaimPatchSchema(ChangeSetInputSchema):
    """Patch body for Title — narrow because most attributes live on Model
    (see [docs/SingleModelTitles.md] for the asymmetric split).
    """

    # See ClaimPatchSchema.fields — polymorphic per claim field, validated downstream.
    fields: dict[str, Any] = {}
    abbreviations: list[str] | None = None


class BlockingReferrerSchema(Schema):
    """An active reference blocking a soft-delete.

    Shared across all lifecycle-entity delete endpoints (Title, Model, …).
    The walker in :mod:`apps.catalog.api.soft_delete` produces these.
    """

    entity_type: str
    slug: str | None = None
    name: str
    relation: str
    blocked_target_type: str
    blocked_target_slug: str | None = None


class SoftDeleteBlockedSchema(Schema):
    """422 response from delete endpoints when active referrers block.

    ``blocked_by`` is empty (list, not null) when the block comes from an
    active-children count rather than PROTECT referrers — the frontend's
    delete-flow classifier relies on ``blocked_by`` being present as an array
    to recognise a blocked outcome. Required (no default) so that Pydantic
    union dispatch against :class:`AlreadyDeletedSchema` routes bare-``detail``
    bodies to the latter instead of filling an empty default here.
    """

    detail: str
    blocked_by: list[BlockingReferrerSchema]
    active_children_count: int = 0


class AlreadyDeletedSchema(Schema):
    """422 response from a delete endpoint when the entity is already soft-deleted.

    Paired with :class:`SoftDeleteBlockedSchema` / :class:`PersonSoftDeleteBlockedSchema`
    in a union on the 422 slot: ``blocked_by`` is absent here, so the frontend's
    delete-flow classifier falls through to ``form_error`` rather than ``blocked``.
    ``extra='forbid'`` forces Pydantic union dispatch to reject bodies carrying
    ``blocked_by`` and route them to the blocked-schema arm instead.
    """

    model_config = ConfigDict(extra="forbid")

    detail: str


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


class DeletePreviewBaseSchema(Schema):
    """Common shape for every entity delete-preview response.

    ``blocked_by`` lists active PROTECT referrers from the generic
    soft-delete walker. Subclasses extend this with entity-specific count
    fields whose semantics the generic shape can't express — typically
    either (a) a blocker count that lives outside ``blocked_by`` because
    the relationship isn't a PROTECT FK the walker can see, or (b) a
    cascade-impact count surfaced so the UI can warn what else will be
    deleted. Those fields are deliberately not collapsed into a single
    shared name: same int shape can mean very different things to the
    consuming UI.
    """

    name: str
    slug: str
    changeset_count: int
    blocked_by: list[BlockingReferrerSchema] = []


class ModelDeletePreviewSchema(DeletePreviewBaseSchema):
    parent: EntityRef


class TaxonomyDeletePreviewSchema(DeletePreviewBaseSchema):
    parent: EntityRef | None = None
    # 0 on leaf entities; non-zero only for parents (tech-gen, display-type)
    # whose active children would block the delete.
    active_children_count: int = 0


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


class DeleteResponseSchema(Schema):
    """Success body for entity soft-delete.

    Shared by taxonomy, machine-model, and person delete endpoints.
    ``affected_slugs`` lists the slugs of entities of the deleted type that
    were soft-deleted in the operation (the target plus any owned cascade
    children of the same type). Title delete is structurally different —
    it cascades into a different type (machine models) — and uses its own
    response schema.
    """

    changeset_id: int
    affected_slugs: list[str]


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
