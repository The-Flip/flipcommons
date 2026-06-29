"""Catalog's resolve handlers, registered into the provenance dispatch seam.

The two public entry points live in :mod:`apps.provenance.resolution`; this
module provides catalog's concrete implementations of that seam's
:class:`~apps.provenance.resolution.PerEntityResolver` and
:class:`~apps.provenance.resolution.BulkResolver` contracts, plus
:func:`register_catalog_resolve_handlers`, which registers them for every
catalog model at ``CatalogConfig.ready()``. The handlers route to the correct
resolver(s) based on entity type and the claim field names that changed; the
per-entity handler also invalidates cached endpoint data (the bulk handler does
not — the bulk caller invalidates once after its run).

Relationship namespaces resolve through one ``(field_name, model) →
RegistryEntry`` table (:func:`_get_relationship_registry`): each entry pairs a
:class:`~apps.catalog.resolve._engine.Projection` builder with a
:class:`~apps.provenance.model_bases.ScopePolicy`, and :func:`resolve_relationship` runs the shared
:func:`~apps.catalog.resolve._engine.reconcile` over it. ``media_attachment`` is
content-type keyed and handled separately (in :mod:`._media`).
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from functools import partial
from typing import Any, NamedTuple

from django.db import transaction

from apps.core.types import ClaimFieldName, ClaimSubjectId
from apps.provenance.model_bases import ScopePolicy, all_relationship_bindings
from apps.provenance.models import ClaimControlledModel

from ..cache import invalidate_response_cache
from ..engine.aliases import discover_alias_types
from ._engine import Projection, reconcile

# ---------------------------------------------------------------------------
# Relationship registry — one (field_name, model) → projection table
# ---------------------------------------------------------------------------


class RelationshipDispatchKey(NamedTuple):
    """Key for the relationship registry.

    The conceptual identity of a relationship resolver is the *pair*
    ``(field_name, entity_model)``, not the ``field_name`` alone: ``credit``
    resolves differently for ``MachineModel`` and ``Series``, and
    ``abbreviation`` differently for ``MachineModel`` and ``Title``.
    """

    field_name: ClaimFieldName
    entity_model: type[ClaimControlledModel]


type ProjectionBuilder = Callable[[], Projection[ClaimSubjectId, Any, Any] | None]
"""Builds a fresh projection for a relationship namespace on each resolve (so
valid-PK sets stay current), or ``None`` to skip the namespace — e.g. credits
when the ``CreditRole`` vocabulary is unseeded. ``Member`` and ``Payload`` are
``Any`` because they vary across namespaces; the registry holds heterogeneous
projections."""


class RegistryEntry(NamedTuple):
    """A relationship namespace's projection builder paired with its scope policy.

    Only entity-``object_id``-keyed projections are registered here; the
    content-type-keyed media projection resolves on its own path.
    """

    build: ProjectionBuilder
    scope: ScopePolicy


_relationship_registry: dict[RelationshipDispatchKey, RegistryEntry] | None = None


def _get_relationship_registry() -> dict[RelationshipDispatchKey, RegistryEntry]:
    """Build the ``(field_name, model) → RegistryEntry`` table lazily.

    Built post-``ready()`` and never snapshotted at module level: this module is
    imported during ``CatalogConfig.ready`` *before* ``register_alias_types``
    populates the alias registry, so a module-level ``discover_alias_types()``
    would freeze an empty result. Holds projection builders (not instances) so
    each resolve sees fresh valid-PK sets.
    """
    global _relationship_registry
    if _relationship_registry is not None:
        return _relationship_registry

    from ..models import GameplayFeature, Theme
    from ._relationships import _alias_projection, _parent_projection
    from ._through_projection import build_through_projection

    registry: dict[RelationshipDispatchKey, RegistryEntry] = {}

    def add(
        field_name: ClaimFieldName,
        model: type[ClaimControlledModel],
        build: ProjectionBuilder,
        scope: ScopePolicy = ScopePolicy.SUBJECTS,
    ) -> None:
        registry[RelationshipDispatchKey(field_name, model)] = RegistryEntry(
            build, scope
        )

    # Explicit through-model namespaces (theme, tag, reward_type,
    # gameplay_feature, credit, abbreviation, location) — one entry per
    # (namespace, subject), driven off the binding's spec. The scope rides the
    # spec, and credit's XOR subject yields one binding per subject FK.
    for binding in all_relationship_bindings():
        add(
            binding.spec.namespace,
            binding.subject_model,
            partial(build_through_projection, binding),
            binding.spec.scope,
        )

    # Aliases — discovered dynamically; resolve whole-type.
    for at in discover_alias_types():
        add(
            at.claim_field,
            at.parent_model,
            partial(_alias_projection, at.parent_model),
            ScopePolicy.FULL_TYPE,
        )

    # Parent hierarchies — resolve whole-type.
    add(
        "theme_parent", Theme, partial(_parent_projection, Theme), ScopePolicy.FULL_TYPE
    )
    add(
        "gameplay_feature_parent",
        GameplayFeature,
        partial(
            _parent_projection, GameplayFeature, claim_field_prefix="gameplay_feature"
        ),
        ScopePolicy.FULL_TYPE,
    )

    _relationship_registry = registry
    return _relationship_registry


def resolve_relationship(
    model: type[ClaimControlledModel],
    field_name: ClaimFieldName,
    *,
    subject_ids: set[ClaimSubjectId] | None = None,
) -> bool:
    """Resolve one relationship namespace via its registered projection.

    Looks up the ``(field_name, model)`` projection, builds it fresh (so
    valid-PK sets are current) and runs :func:`reconcile`. ``FULL_TYPE``
    namespaces (aliases, parent hierarchies) ignore *subject_ids* and resolve
    their whole type. Returns ``True`` if a projection handled the namespace,
    ``False`` if none is registered — the caller decides whether that is media,
    a no-op (per-entity) or an error (bulk).
    """
    entry = _get_relationship_registry().get(RelationshipDispatchKey(field_name, model))
    if entry is None:
        return False
    projection = entry.build()
    if projection is not None:
        scope = subject_ids if entry.scope is ScopePolicy.SUBJECTS else None
        # reconcile returns a Delta (for cache scoping); unused here.
        reconcile(projection, scope)
    return True


# ---------------------------------------------------------------------------
# Registration into the provenance dispatch seam
# ---------------------------------------------------------------------------


def _per_entity_handler(
    entity: ClaimControlledModel,
    field_names: list[ClaimFieldName] | None = None,
) -> None:
    """Per-entity resolve handler — catalog's ``PerEntityResolver``.

    Re-resolves one entity after its claims have been mutated, then schedules
    cache invalidation. Runs synchronously inside the caller's transaction.

    Parameters
    ----------
    entity:
        The catalog entity whose claims changed.
    field_names:
        The claim ``field_name`` values that were mutated (scalar and
        relationship both).  When ``None``, all applicable resolvers run
        (safe but less efficient).
    """
    _resolve_entity_relationships(entity, field_names)

    transaction.on_commit(invalidate_response_cache)


def _bulk_handler(
    model_class: type[ClaimControlledModel],
    subject_ids: set[ClaimSubjectId],
    field_names: Collection[ClaimFieldName],
) -> None:
    """Bulk resolve handler — catalog's ``BulkResolver``.

    Re-resolves scalar/FK fields for the whole subject set, then the changed
    relationship namespaces in a single pass each. Does **not** invalidate
    caches — the bulk caller invalidates once after its run.
    """
    from ._entities import resolve_all_entities

    resolve_all_entities(model_class, object_ids=subject_ids)
    resolve_relationships_bulk(model_class, field_names, subject_ids)


def register_catalog_resolve_handlers() -> None:
    """Register catalog's resolve handlers for every catalog model.

    Called from ``CatalogConfig.ready()``. Iterates the catalog-scoped
    ``catalog_models()`` walk (every concrete ``CatalogModel`` — which is
    exactly catalog's claim-controlled set) and registers the same generic
    handler pair for each, so the provenance dispatch resolves any catalog
    model and raises for a model no domain has claimed.
    """
    from apps.provenance.resolution import ResolveHandlers, register_resolve_handlers

    from .._walks import catalog_models

    handlers = ResolveHandlers(per_entity=_per_entity_handler, bulk=_bulk_handler)
    for model in catalog_models():
        register_resolve_handlers(model, handlers)


# ---------------------------------------------------------------------------
# Internal routing
# ---------------------------------------------------------------------------


def _resolve_entity_relationships(
    entity: ClaimControlledModel,
    field_names: list[ClaimFieldName] | None,
) -> None:
    """Per-entity path — dispatch relationship resolvers then scalars."""
    from apps.provenance.validation import get_relationship_namespaces

    from ._entities import resolve_entity

    relationship_ns = get_relationship_namespaces()
    entity_type = type(entity)
    registry = _get_relationship_registry()

    if field_names is not None:
        rel_fields = [fn for fn in field_names if fn in relationship_ns]
    else:
        rel_fields = None  # signals "run all applicable"

    # --- Relationship namespaces (aliases, parents, m2m, credits, …) ---
    # Unhandled namespaces are a no-op here (lenient per-entity path); the bulk
    # path fails loudly instead.  media_attachment is not in the registry and is
    # handled separately below.
    if rel_fields is not None:
        for fn in rel_fields:
            resolve_relationship(entity_type, fn, subject_ids={entity.pk})
    else:
        for key in registry:
            if key.entity_model is entity_type:
                resolve_relationship(
                    entity_type, key.field_name, subject_ids={entity.pk}
                )

    # --- Media attachments (content-type keyed, not in the registry) ---
    from apps.media.models import MediaSupportedModel

    if isinstance(entity, MediaSupportedModel) and (
        rel_fields is None or "media_attachment" in rel_fields
    ):
        from django.contrib.contenttypes.models import ContentType

        from ._media import resolve_media_attachments

        ct = ContentType.objects.get_for_model(entity_type)
        resolve_media_attachments(content_type_id=ct.id, subject_ids={entity.pk})

    # --- Scalar fields ---
    resolve_entity(entity)


# ---------------------------------------------------------------------------
# Bulk relationship resolution (the relationship half of ``_bulk_handler``)
# ---------------------------------------------------------------------------


def resolve_relationships_bulk(
    model_class: type[ClaimControlledModel],
    field_names: Collection[ClaimFieldName],
    subject_ids: set[ClaimSubjectId],
) -> None:
    """Bulk re-resolve relationship namespaces for many subjects in one pass.

    The batched equivalent of calling the per-entity handler once per object
    for relationship fields. :func:`_bulk_handler` calls this after
    ``resolve_all_entities`` has bulk-resolved scalar/FK fields; this covers
    only the relationship namespaces.

    Unlike :func:`_per_entity_handler`, this does NOT register an ``on_commit``
    cache invalidation — the caller invalidates once after the run (the
    ``ingest_patches`` command does, as does the apply engine's caller).

    Raises ``ValueError`` for a namespace with no registered projection on
    *model_class*, so an unhandled relationship fails loudly instead of leaving
    its claims silently unresolved.
    """
    if not subject_ids or not field_names:
        return

    for fn in field_names:
        if fn == "media_attachment":
            _resolve_media_bulk(model_class, subject_ids)
        elif not resolve_relationship(model_class, fn, subject_ids=subject_ids):
            raise ValueError(
                f"No bulk resolver for relationship {fn!r} on {model_class.__name__}"
            )


def _resolve_media_bulk(
    model_class: type[ClaimControlledModel], subject_ids: set[ClaimSubjectId]
) -> None:
    """Bulk-resolve media attachments for a media-supported entity type."""
    from apps.media.models import MediaSupportedModel

    if not issubclass(model_class, MediaSupportedModel):
        return
    from django.contrib.contenttypes.models import ContentType

    from ._media import resolve_media_attachments

    ct = ContentType.objects.get_for_model(model_class)
    resolve_media_attachments(content_type_id=ct.id, subject_ids=subject_ids)
