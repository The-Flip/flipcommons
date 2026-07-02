"""Generic delete / restore wiring for lifecycle entities.

The delete-preview, delete and restore routes for any
``LinkableLifecycleClaimModel``. Entity-specific shapes (detail queryset,
serializer, restore response schema) are injected as callables so the same
helpers wire routes for taxonomy entities *and* the richer Theme /
GameplayFeature / Series / Franchise / System schemas without duplicating code.

Unlike the create registrar — whose closure handlers carry a closure-bound
``data: request_body_schema`` annotation that forces eager evaluation — the
delete/restore handlers annotate ``data`` with the module-global
``ChangeSetInputSchema``, which Ninja resolves either way. ``from __future__
import annotations`` is omitted here only for consistency with that sibling, not
out of necessity.
"""

from collections.abc import Callable

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.responses import Status
from ninja.security import django_auth

from apps.claim_edit.claim_write import ClaimSpec, execute_claims
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.models import is_deleted
from apps.core.schemas import ErrorDetailSchema, RateLimitErrorSchema
from apps.provenance.models import ChangeSetAction, LinkableLifecycleClaimModel
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    rate_limited,
)
from apps.provenance.schemas import ChangeSetInputSchema

from ...schemas import EntityRef
from .schemas import (
    AlreadyDeletedSchema,
    DeleteResponseSchema,
    EntityDeletePreviewSchema,
    SoftDeleteBlockedSchema,
)
from .soft_delete import (
    SoftDeleteBlockedError,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)


# ``ModelT`` / ``SchemaT`` link the four contractually-related arguments
# — model class, detail queryset, serializer, response schema must agree.
def register_entity_delete_restore[
    ModelT: LinkableLifecycleClaimModel,
    SchemaT: Schema,
](
    router: Router,
    model_cls: type[ModelT],
    *,
    detail_qs: Callable[[], QuerySet[ModelT]],
    serialize_detail: Callable[[ModelT], SchemaT],
    response_schema: type[SchemaT],
    child_related_name: str | None = None,
    parent_field: str | None = None,
) -> None:
    """Attach delete-preview, delete, and restore routes to *router*.

    * ``detail_qs`` — callable returning the prefetched queryset used to
      re-read the entity after restore, passed to the response serializer.
    * ``serialize_detail`` — callable that converts an entity instance to a
      wire dict. For taxonomy this is a shared helper; Theme / GameplayFeature
      / Series inject their own detail serializers.
    * ``response_schema`` — Ninja schema used for restore's 200 body. Restore
      responds with the entity's full detail shape.
    * ``child_related_name`` — set on entities with active-child blocking
      (tech-gen → subgenerations, display-type → subtypes). The accessor
      name is the ``related_name=`` declared on the child FK.
    * ``parent_field`` — set on entities whose parent FK should drive the
      preview's parent ref and the restore-while-parent-deleted guard
      (subgen/subtype, Location). Nullable parent FKs are tolerated:
      rows with ``parent=None`` (e.g. Location countries) skip both
      checks rather than dereferencing a missing row.
    """
    entity_label = model_cls.__name__
    friendly = model_cls.entity_type.replace("-", " ")
    friendly_sentence = friendly.capitalize()
    public_id_field = model_cls.public_id_field

    def _delete_preview(
        request: HttpRequest, public_id: str
    ) -> EntityDeletePreviewSchema:
        obj = get_object_or_404(
            model_cls.objects.active(), **{public_id_field: public_id}
        )
        plan = plan_soft_delete(obj)

        active_children = 0
        if child_related_name is not None:
            active_children = getattr(obj, child_related_name).active().count()

        is_blocked = plan.is_blocked or active_children > 0
        changeset_count = 0 if is_blocked else count_entity_changesets(obj)

        parent_ref: EntityRef | None = None
        if parent_field is not None:
            # Parent FK may be nullable (e.g. Location countries have
            # ``parent=None``); leave ``parent_ref`` as ``None`` in that
            # case rather than dereferencing a missing row.
            parent = getattr(obj, parent_field)
            if parent is not None:
                parent_ref = EntityRef(name=parent.name, public_id=parent.public_id)

        return EntityDeletePreviewSchema(
            name=obj.name,
            slug=obj.slug,
            parent=parent_ref,
            changeset_count=changeset_count,
            blocked_by=[serialize_blocking_referrer(b) for b in plan.blockers],
            active_children_count=active_children,
        )

    _delete_preview.__name__ = f"{entity_label.lower()}_delete_preview"
    router.get(
        "/{path:public_id}/delete-preview/",
        auth=django_auth,
        response=EntityDeletePreviewSchema,
        tags=["private"],
    )(_delete_preview)

    def _delete(
        request: HttpRequest, public_id: str, data: ChangeSetInputSchema
    ) -> DeleteResponseSchema | Status[SoftDeleteBlockedSchema | AlreadyDeletedSchema]:
        obj = get_object_or_404(
            model_cls.objects.active(), **{public_id_field: public_id}
        )

        if child_related_name is not None:
            active_children = getattr(obj, child_related_name).active().count()
            if active_children > 0:
                # The empty ``blocked_by`` array is required — the shared
                # frontend classifier in delete-flow.ts only treats a 422
                # as a ``blocked`` outcome when ``blocked_by`` is present
                # as an array; otherwise it falls through to a generic
                # form error and loses the structured state.
                return Status(
                    422,
                    SoftDeleteBlockedSchema(
                        detail=(
                            f"Cannot delete: {obj.name} has {active_children} "
                            f"active child"
                            f"{'ren' if active_children != 1 else ''}. "
                            "Delete those first."
                        ),
                        blocked_by=[],
                        active_children_count=active_children,
                    ),
                )

        try:
            changeset, deleted = execute_soft_delete(
                obj, user=request.user, note=data.note, citations=data.citations
            )
        except SoftDeleteBlockedError as exc:
            return Status(
                422,
                SoftDeleteBlockedSchema(
                    detail=("Cannot delete: active references would be left dangling."),
                    blocked_by=[serialize_blocking_referrer(b) for b in exc.blockers],
                    active_children_count=0,
                ),
            )

        if changeset is None:
            return Status(
                422,
                AlreadyDeletedSchema(detail=f"{friendly_sentence} is already deleted."),
            )

        return DeleteResponseSchema(
            changeset_id=changeset.pk,
            affected_slugs=[e.slug for e in deleted if isinstance(e, model_cls)],
        )

    _delete.__name__ = f"{entity_label.lower()}_delete"
    _delete = requires(Activity.CATALOG_DELETE)(
        rate_limited(DELETE_RATE_LIMIT_SPEC)(_delete)
    )
    router.post(
        "/{path:public_id}/delete/",
        auth=django_auth,
        response={
            200: DeleteResponseSchema,
            422: SoftDeleteBlockedSchema | AlreadyDeletedSchema,
            429: RateLimitErrorSchema,
        },
        tags=["private"],
    )(_delete)

    def _restore(
        request: HttpRequest, public_id: str, data: ChangeSetInputSchema
    ) -> SchemaT | Status[ErrorDetailSchema]:
        # Bypass .active() — we're looking for soft-deleted rows.
        obj = get_object_or_404(model_cls, **{public_id_field: public_id})
        if not is_deleted(obj.status):
            return Status(
                422, ErrorDetailSchema(detail=f"{friendly_sentence} is not deleted.")
            )

        if parent_field is not None:
            # Parent FK may be nullable (e.g. Location countries have
            # ``parent=None``); skip the parent-status guard in that case.
            parent = getattr(obj, parent_field)
            if parent is not None and is_deleted(parent.status):
                return Status(
                    422, ErrorDetailSchema(detail=f"Restore {parent.name} first.")
                )

        execute_claims(
            obj,
            [ClaimSpec(field_name="status", value="active")],
            user=request.user,
            action=ChangeSetAction.EDIT,
            note=data.note,
            citations=data.citations,
        )

        refreshed = get_object_or_404(detail_qs(), **{public_id_field: public_id})
        return serialize_detail(refreshed)

    _restore.__name__ = f"{entity_label.lower()}_restore"
    # Restore consumes the create rate-limit bucket (it reintroduces a record),
    # so it is classified as CATALOG_CREATE even though the underlying
    # ``execute_claims`` writes action=EDIT. See docs/RecordLifecycle.md.
    _restore = requires(Activity.CATALOG_CREATE)(
        rate_limited(CREATE_RATE_LIMIT_SPEC)(_restore)
    )
    router.post(
        "/{path:public_id}/restore/",
        auth=django_auth,
        response={
            200: response_schema,
            422: ErrorDetailSchema,
            404: ErrorDetailSchema,
            429: RateLimitErrorSchema,
        },
        tags=["private"],
    )(_restore)
