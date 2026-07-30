"""Generic wire schemas for the entity delete / restore surface.

Domain-neutral delete shapes used by the generic delete-restore registrar and
the soft-delete engine. Entity-specific previews (``ModelDeletePreviewSchema``,
``PersonDeletePreviewSchema``, …) subclass :class:`DeletePreviewBaseSchema`
domain-side in ``catalog.api.schemas``.
"""

from __future__ import annotations

from ninja import Schema
from pydantic import ConfigDict

from ...schemas import EntityRef


class BlockingReferrerSchema(Schema):
    """An active reference blocking a soft-delete.

    Shared across all lifecycle-entity delete endpoints (Title, Model, …).
    The walker in :mod:`apps.catalog.engine.entity_api.delete.soft_delete`
    produces these.
    """

    entity_type: str
    public_id: str
    name: str
    relation: str
    blocked_target_type: str
    blocked_target_public_id: str


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

    Paired with :class:`SoftDeleteBlockedSchema` / ``PersonSoftDeleteBlockedSchema``
    in a union on the 422 slot: ``blocked_by`` is absent here, so the frontend's
    delete-flow classifier falls through to ``form_error`` rather than ``blocked``.
    ``extra='forbid'`` forces Pydantic union dispatch to reject bodies carrying
    ``blocked_by`` and route them to the blocked-schema arm instead.
    """

    model_config = ConfigDict(extra="forbid")

    detail: str


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


class EntityDeletePreviewSchema(DeletePreviewBaseSchema):
    """The registrar's generic delete-preview body.

    Built inline by :func:`register_entity_delete_restore` for every entity
    routed through it — flat (Manufacturer, CorporateEntity) and hierarchical
    (Theme, Location, …) alike. Domain-neutral in shape: ``parent`` is a
    generic entity ref and ``active_children_count`` a generic tree count,
    exactly as generic as :class:`DeleteResponseSchema`, so it stays
    engine-side. Entity-specific previews that need bespoke blocking semantics
    (Model / Person / Title) hand-roll their own routes and schemas domain-side.
    """

    parent: EntityRef | None = None
    # 0 on leaf entities; non-zero only for parents (tech-gen, display-type)
    # whose active children would block the delete.
    active_children_count: int = 0


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
