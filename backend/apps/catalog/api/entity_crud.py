"""Generic create / delete / restore wiring for lifecycle catalog entities.

Lifts the shared plumbing originally grown in :mod:`taxonomy` — rate
limiting, name / slug validation and uniqueness, PROTECT-blocker
serialization, soft-delete execution, and restore — into two registrar
functions. Entity-specific shapes (detail queryset, serialize function,
response schema) are injected as callables so the same helpers can wire
routes for taxonomy entities *and* the richer Theme / GameplayFeature /
Series / Franchise / System schemas without duplicating code.

All wire schemas used here — ``CreateSchema``, ``ChangeSetInputSchema``,
``TaxonomyDeletePreviewSchema``, ``DeleteResponseSchema`` — live in the
shared catalog/provenance schema modules. This module owns no schemas of
its own.

.. note::

    This module deliberately does **not** use ``from __future__ import
    annotations``. The closure-defined create handlers below carry a
    ``data: request_body_schema`` annotation where ``request_body_schema``
    is a closure variable bound at registration time. Ninja resolves
    body annotations via ``get_type_hints``, which evaluates string
    annotations against module globals only — so stringified
    annotations would fail to resolve closure-bound types. With eager
    evaluation, the annotation captures the right class at closure
    creation and Ninja sees the per-registration body schema directly.
"""

from collections.abc import Callable
from typing import Any, NamedTuple

from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.responses import Status
from ninja.security import django_auth

from apps.catalog.models import CatalogModel
from apps.claim_edit.claim_write import ClaimSpec, execute_claims
from apps.core.authz.markers import requires
from apps.core.authz.types import Activity
from apps.core.models import is_deleted
from apps.core.schemas import (
    ErrorDetailSchema,
    RateLimitErrorSchema,
    ValidationErrorSchema,
)
from apps.provenance.models import ChangeSetAction
from apps.provenance.rate_limits import (
    CREATE_RATE_LIMIT_SPEC,
    DELETE_RATE_LIMIT_SPEC,
    rate_limited,
)
from apps.provenance.schemas import ChangeSetInputSchema

from .entity_create import (
    assert_public_id_available,
    create_entity_with_claims,
    validate_create_input,
)
from .schemas import (
    AlreadyDeletedSchema,
    DeleteResponseSchema,
    EntityCreateInputSchema,
    EntityRef,
    SoftDeleteBlockedSchema,
    TaxonomyDeletePreviewSchema,
)
from .soft_delete import (
    SoftDeleteBlockedError,
    count_entity_changesets,
    execute_soft_delete,
    plan_soft_delete,
    serialize_blocking_referrer,
)


class CreateExtras(NamedTuple):
    """Return type of ``extra_create_fields_builder``.

    *row_kwargs* are merged into the ``model_cls.objects.create`` call; field
    set varies per caller (e.g. Location supplies ``location_type``,
    ``divisions``, ``location_path``), so it stays as a kwargs dict at the
    Django boundary. *claim_specs* are appended to the create ChangeSet's
    claims.
    """

    row_kwargs: dict[str, Any]
    claim_specs: list[ClaimSpec]


# ---------------------------------------------------------------------------
# Registrars
# ---------------------------------------------------------------------------


# ``ModelT`` / ``SchemaT`` link the four contractually-related arguments
# — model class, detail queryset, serializer, response schema must agree.
def register_entity_delete_restore[ModelT: CatalogModel, SchemaT: Schema](
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
    ) -> TaxonomyDeletePreviewSchema:
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

        return TaxonomyDeletePreviewSchema(
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
        response=TaxonomyDeletePreviewSchema,
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
                obj, user=request.user, note=data.note, citation=data.citation
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
            citation=data.citation,
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


def register_entity_create[ModelT: CatalogModel, SchemaT: Schema](
    router: Router,
    model_cls: type[ModelT],
    *,
    detail_qs: Callable[[], QuerySet[ModelT]],
    serialize_detail: Callable[[ModelT], SchemaT],
    response_schema: type[SchemaT],
    parent_field: str | None = None,
    parent_model: type[CatalogModel] | None = None,
    route_suffix: str = "",
    scope_filter_builder: Callable[[EntityCreateInputSchema, CatalogModel | None], Q]
    | None = None,
    include_deleted_name_check: bool | None = None,
    body_schema: type[EntityCreateInputSchema] | None = None,
    extra_create_fields_builder: Callable[
        [EntityCreateInputSchema, CatalogModel | None],
        CreateExtras,
    ]
    | None = None,
    op_id_suffix: str = "",
) -> None:
    """Attach a POST create route.

    When *parent_field* is None, mounts ``POST /`` on the entity's own
    router. Otherwise all three parent-related args must be supplied
    together and the route mounts at
    ``POST /{path:parent_public_id}/<route_suffix>/`` on the *parent's*
    router — mirroring the Title → Model nesting.

    .. note:: When to add a new hook here

        The factory's value is **guaranteed convergence**: every catalog
        create routes through one pipeline, so two callers can't drift.
        A new keyword-only hook is justified when a caller needs a
        contained variation on that pipeline (e.g. a derived column, a
        custom body field) and the alternative is a parallel handler
        that copies 80%+ of this code. Single-caller hooks are fine on
        that basis — they keep the caller on the canonical path.

        A new hook is *not* justified for hypothetical future callers
        (no current caller, no hook). For entities whose create is
        *structurally* different — different transactional shape,
        different side effects, fundamentally different unit of work —
        write a custom handler over the primitives in
        :mod:`apps.catalog.api.entity_create` (``validate_create_input``,
        ``assert_public_id_available``, ``create_entity_with_claims``,
        …) instead of extending this factory.

    FK claim values come from ``model_cls.claim_fk_lookups`` (defaults to
    the parent's ``slug`` when unset; Location overrides ``parent`` to
    ``location_path``). Hardcoding ``parent.slug`` anywhere on the write
    path is a field-on-model antipattern.

    *scope_filter_builder* narrows the name-collision scan to a subset
    of rows. Required for entities whose names are unique per-parent
    rather than globally (e.g. CorporateEntity: two manufacturers may
    each own a "Productions" entity, but not the same manufacturer), and
    for unparented sibling-scoped tiers (e.g. top-level Location:
    ``Q(parent__isnull=True)`` keeps the country-tier check from
    scanning every descendant). Receives the parsed body schema and the
    resolved parent (``None`` in unparented mode) and returns a ``Q`` to
    pass to ``assert_name_available``.

    *include_deleted_name_check* forwards to ``assert_name_available``'s
    ``include_deleted``. Defaults to ``True`` whenever the model carries
    a DB-unique constraint on ``name`` (either ``unique=True`` on the
    field or a ``UniqueConstraint`` covering it) so a soft-deleted-name
    collision surfaces as a name error before the insert. Pass an
    explicit bool to override.

    *body_schema* replaces ``EntityCreateInputSchema`` as the request
    body type. Constrained to subclasses (the factory reads ``data.name``,
    ``data.slug``, ``data.note``, ``data.citation``) so a non-conforming
    schema fails at registration. Used by Location's top-level country
    create to accept ``divisions`` alongside the standard fields.

    Callers: Location top-level country create only. Re-evaluate
    naming / shape if a second caller appears with a different
    extension pattern.

    *extra_create_fields_builder* returns ``(extra_row_kwargs,
    extra_claim_specs)``. The row kwargs are merged into the row
    ``model_cls.objects.create`` call; the claim specs are appended to
    the per-create claim list. One builder rather than two so callers
    derive shared values once (e.g. Location derives ``location_type``
    and uses it both as a row column and as a claim).

    Callers: Location top-level + child create only. Re-evaluate the
    tuple-return shape vs. a ``CreateExtras`` dataclass if a second
    caller appears.

    *op_id_suffix* is appended to the OpenAPI ``operationId`` for this
    route. Used by entities that register the factory twice on the same
    router (Location: top-level country + child) so the two routes don't
    collide on the default name. Empty by default — every other caller
    keeps the stable ``{entity}_create`` op_id.

    Callers: Location's child create only (passes ``"_child"``).
    """
    parented = parent_field is not None
    if parented and not (parent_model and route_suffix):
        raise TypeError(
            "register_entity_create: when parent_field is set, "
            "parent_model and route_suffix are required."
        )
    if body_schema is not None and not issubclass(body_schema, EntityCreateInputSchema):
        # The factory's pipeline reads ``data.name``, ``data.slug``,
        # ``data.note``, ``data.citation``. mypy enforces this at the
        # type level via the ``type[EntityCreateInputSchema]`` annotation,
        # but bypassing the type checker (e.g. dynamic dispatch in tests)
        # would silently register a route that 500s on the first request.
        # Fail loudly at registration instead.
        raise TypeError(
            f"register_entity_create: body_schema must subclass "
            f"EntityCreateInputSchema; got {body_schema.__name__}."
        )

    entity_label = model_cls.__name__
    parent_lookup_field: str | None = None
    if parent_field is not None and parent_model is not None:
        parent_lookup_field = parent_model.public_id_field
    request_body_schema: type[EntityCreateInputSchema] = (
        body_schema if body_schema is not None else EntityCreateInputSchema
    )

    def _do_create(
        request: HttpRequest,
        data: EntityCreateInputSchema,
        parent: CatalogModel | None = None,
    ) -> Status[SchemaT]:
        scope_filter = (
            scope_filter_builder(data, parent)
            if scope_filter_builder is not None
            else None
        )
        name, slug = validate_create_input(
            data,
            model_cls,
            scope_filter=scope_filter,
            include_deleted_name_check=include_deleted_name_check,
        )

        row_kwargs: dict[str, Any] = {"name": name, "slug": slug, "status": "active"}
        claim_specs = [
            ClaimSpec(field_name="name", value=name),
            ClaimSpec(field_name="slug", value=slug),
            ClaimSpec(field_name="status", value="active"),
        ]
        if parent is not None:
            assert parent_field is not None
            row_kwargs[parent_field] = parent
            # FK claim value reads from claim_fk_lookups (defaults to parent's
            # slug); models override per-field when the parent's identity
            # lives on a non-slug field.
            fk_lookup = model_cls.claim_fk_lookups.get(parent_field, "slug")
            claim_specs.append(
                ClaimSpec(field_name=parent_field, value=getattr(parent, fk_lookup))
            )

        if extra_create_fields_builder is not None:
            extras = extra_create_fields_builder(data, parent)
            row_kwargs.update(extras.row_kwargs)
            claim_specs.extend(extras.claim_specs)

        # Pre-check the public-id column (slug for shipped models;
        # location_path for Location). Runs after extra_create_fields_builder
        # so derived public-ids (Location: ``compute_location_path``) are
        # populated in row_kwargs before the lookup. ``form_value`` is the
        # user-typed value the error message echoes; for shipped models
        # this is the same as the public-id (both ``slug``), for Location
        # it's the bare ``slug`` rather than the full path.
        public_id_value = row_kwargs[model_cls.public_id_field]
        form_field = model_cls.public_id_form_field or model_cls.public_id_field
        form_value = row_kwargs.get(form_field, public_id_value)
        assert_public_id_available(model_cls, public_id_value, form_value=form_value)

        entity = create_entity_with_claims(
            model_cls,
            row_kwargs=row_kwargs,
            claim_specs=claim_specs,
            user=request.user,
            note=data.note,
            citation=data.citation,
        )

        # Refetch via the prefetch-rich ``detail_qs`` for serialization.
        # Use pk (not public_id_field) — the freshly inserted row's pk is
        # the most reliable handle and does not depend on whether
        # ``public_id_field`` was populated synchronously by
        # ``model_cls.objects.create``.
        created = get_object_or_404(detail_qs(), pk=entity.pk)
        return Status(201, serialize_detail(created))

    if parented:
        assert parent_model is not None
        assert parent_lookup_field is not None

        def _create_parented(
            request: HttpRequest,
            parent_public_id: str,
            data: request_body_schema,  # type: ignore[valid-type]
        ) -> Status[SchemaT]:
            parent = get_object_or_404(
                parent_model.objects.active(),
                **{parent_lookup_field: parent_public_id},
            )
            return _do_create(request, data, parent=parent)

        _create_parented.__name__ = f"{entity_label.lower()}_create{op_id_suffix}"
        _create_parented = requires(Activity.CATALOG_CREATE)(
            rate_limited(CREATE_RATE_LIMIT_SPEC)(_create_parented)
        )
        router.post(
            f"/{{path:parent_public_id}}/{route_suffix}/",
            auth=django_auth,
            response={
                201: response_schema,
                422: ValidationErrorSchema,
                429: RateLimitErrorSchema,
            },
            tags=["private"],
        )(_create_parented)
    else:

        def _create_unparented(
            request: HttpRequest,
            data: request_body_schema,  # type: ignore[valid-type]
        ) -> Status[SchemaT]:
            return _do_create(request, data)

        _create_unparented.__name__ = f"{entity_label.lower()}_create{op_id_suffix}"
        _create_unparented = requires(Activity.CATALOG_CREATE)(
            rate_limited(CREATE_RATE_LIMIT_SPEC)(_create_unparented)
        )
        router.post(
            "/",
            auth=django_auth,
            response={
                201: response_schema,
                422: ValidationErrorSchema,
                429: RateLimitErrorSchema,
            },
            tags=["private"],
        )(_create_unparented)
