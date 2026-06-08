"""Centralised resolution dispatch after claim mutations.

Provides :func:`resolve_after_mutation` — a single entry-point that any
module (including provenance) can call after mutating claims on an entity.
Internally it routes to the correct resolver(s) based on entity type and
the claim field names that changed, then invalidates cached endpoint data.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import NamedTuple, cast

from django.db import transaction

from apps.provenance.models import ClaimControlledModel

from .._alias_registry import discover_alias_types
from ..cache import invalidate_all

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dispatch tables — built lazily to avoid import-time model access
# ---------------------------------------------------------------------------


class ParentDispatchSpec(NamedTuple):
    """Entry in the parent-hierarchy dispatch table."""

    model: type[ClaimControlledModel]
    claim_field_prefix: str | None


class CustomDispatchSpec(NamedTuple):
    """Entry in the custom-resolver dispatch table.

    Each entry specifies which model type it applies to and which
    ``resolve_all_*`` function to call.  Every bespoke resolver takes
    the canonical ``subject_ids`` kwarg.
    """

    entity_model: type
    resolver_function_name: str


_alias_dispatch: dict[str, type] | None = None


def _get_alias_dispatch() -> dict[str, type]:
    """field_name → parent model class for alias resolvers."""
    global _alias_dispatch
    if _alias_dispatch is None:
        _alias_dispatch = {
            at.claim_field: at.parent_model for at in discover_alias_types()
        }
    return _alias_dispatch


_parent_dispatch: dict[str, ParentDispatchSpec] | None = None


def _get_parent_dispatch() -> dict[str, ParentDispatchSpec]:
    """field_name → ParentDispatchSpec for _resolve_parents()."""
    global _parent_dispatch
    if _parent_dispatch is None:
        from ..models import GameplayFeature, Theme

        _parent_dispatch = {
            "theme_parent": ParentDispatchSpec(Theme, None),
            "gameplay_feature_parent": ParentDispatchSpec(
                GameplayFeature, "gameplay_feature"
            ),
        }
    return _parent_dispatch


_custom_dispatch: dict[str, CustomDispatchSpec] | None = None


def _get_custom_dispatch() -> dict[str, CustomDispatchSpec]:
    """field_name → CustomDispatchSpec for entity-specific resolvers."""
    global _custom_dispatch
    if _custom_dispatch is None:
        from ..models import CorporateEntity, Title

        _custom_dispatch = {
            "abbreviation": CustomDispatchSpec(
                Title, "resolve_all_title_abbreviations"
            ),
            "location": CustomDispatchSpec(
                CorporateEntity,
                "resolve_all_corporate_entity_locations",
            ),
        }
    return _custom_dispatch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_after_mutation(
    entity: ClaimControlledModel,
    field_names: list[str] | None = None,
) -> None:
    """Re-resolve an entity after its claims have been mutated.

    Call this inside a ``transaction.atomic()`` block after creating,
    deactivating, or modifying claims.  Resolution runs synchronously
    inside the caller's transaction.  Cache invalidation runs after
    resolution completes.

    Parameters
    ----------
    entity:
        The catalog entity whose claims changed.
    field_names:
        The claim ``field_name`` values that were mutated.  When ``None``,
        all applicable resolvers run (safe but less efficient).
    """
    from ..models import MachineModel

    if isinstance(entity, MachineModel):
        _resolve_machine_model(entity)
    else:
        _resolve_non_machine_model(entity, field_names)

    transaction.on_commit(invalidate_all)


# ---------------------------------------------------------------------------
# Internal routing
# ---------------------------------------------------------------------------


def _resolve_machine_model(entity: ClaimControlledModel) -> None:
    """MachineModel path — resolve_model() handles everything."""
    from ..models import MachineModel
    from . import resolve_model

    resolve_model(cast(MachineModel, entity))


def _resolve_non_machine_model(
    entity: ClaimControlledModel,
    field_names: list[str] | None,
) -> None:
    """Non-MachineModel path — dispatch relationship resolvers then scalars."""
    from ..claims import get_relationship_namespaces
    from ._entities import resolve_entity
    from ._media import resolve_media_attachments
    from ._relationships import _resolve_aliases, _resolve_parents

    relationship_ns = get_relationship_namespaces()
    entity_type = type(entity)

    if field_names is not None:
        rel_fields = [fn for fn in field_names if fn in relationship_ns]
    else:
        rel_fields = None  # signals "run all applicable"

    # --- Alias resolvers ---
    alias_dispatch = _get_alias_dispatch()
    if rel_fields is not None:
        for fn in rel_fields:
            if fn in alias_dispatch and alias_dispatch[fn] is entity_type:
                _resolve_aliases(alias_dispatch[fn])
    else:
        for parent_model in alias_dispatch.values():
            if parent_model is entity_type:
                _resolve_aliases(parent_model)

    # --- Parent hierarchy resolvers ---
    parent_dispatch = _get_parent_dispatch()
    if rel_fields is not None:
        for fn in rel_fields:
            if fn in parent_dispatch:
                spec = parent_dispatch[fn]
                if spec.model is entity_type:
                    _resolve_parents(
                        spec.model, claim_field_prefix=spec.claim_field_prefix
                    )
    else:
        for spec in parent_dispatch.values():
            if spec.model is entity_type:
                _resolve_parents(spec.model, claim_field_prefix=spec.claim_field_prefix)

    # --- Custom resolvers (abbreviation, location) ---
    custom_dispatch = _get_custom_dispatch()
    if rel_fields is not None:
        for fn in rel_fields:
            if (
                fn in custom_dispatch
                and custom_dispatch[fn].entity_model is entity_type
            ):
                _call_custom_resolver(custom_dispatch[fn], entity.pk)
    else:
        for custom_spec in custom_dispatch.values():
            if custom_spec.entity_model is entity_type:
                _call_custom_resolver(custom_spec, entity.pk)

    # --- Media attachments ---
    from apps.media.models import MediaSupportedModel

    if isinstance(entity, MediaSupportedModel) and (
        rel_fields is None or "media_attachment" in rel_fields
    ):
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(entity_type)
        resolve_media_attachments(content_type_id=ct.id, subject_ids={entity.pk})

    # --- Scalar fields ---
    resolve_entity(entity)


def _call_custom_resolver(spec: CustomDispatchSpec, entity_pk: int) -> None:
    """Call a custom resolver by name with scoped IDs."""
    from . import _relationships

    func = getattr(_relationships, spec.resolver_function_name)
    func(subject_ids={entity_pk})


# ---------------------------------------------------------------------------
# Bulk relationship resolution (for ingest/patch resolve hooks)
# ---------------------------------------------------------------------------


_mm_relationship_resolvers: dict[str, Callable[..., None]] | None = None


def _get_mm_relationship_resolvers() -> dict[str, Callable[..., None]]:
    """namespace → bulk resolver for MachineModel relationship claims.

    Mirrors the relationship resolvers in ``resolve.resolve_model()``; each
    takes ``subject_ids`` so an entire affected set resolves in a single pass.
    Keyed explicitly (not introspected) because the resolver per namespace is
    inherently bespoke — same rationale as the dispatch tables above. (Media
    is handled separately; it is keyed by content type, not a per-model M2M.)
    """
    global _mm_relationship_resolvers
    if _mm_relationship_resolvers is None:
        from ._relationships import (
            resolve_all_credits,
            resolve_all_gameplay_features,
            resolve_all_model_abbreviations,
            resolve_all_reward_types,
            resolve_all_tags,
            resolve_all_themes,
        )

        _mm_relationship_resolvers = {
            "credit": resolve_all_credits,
            "theme": resolve_all_themes,
            "gameplay_feature": resolve_all_gameplay_features,
            "reward_type": resolve_all_reward_types,
            "tag": resolve_all_tags,
            "abbreviation": resolve_all_model_abbreviations,
        }
    return _mm_relationship_resolvers


def resolve_relationships_bulk(
    model_class: type[ClaimControlledModel],
    field_names: list[str],
    subject_ids: set[int],
) -> None:
    """Bulk re-resolve relationship namespaces for many subjects in one pass.

    The batched equivalent of calling :func:`resolve_after_mutation` once per
    object for relationship fields. The ingest apply engine already
    bulk-resolves scalar/FK fields (``resolve_all_entities``); this covers only
    the relationship namespaces, which is all a data patch's resolve hook needs.

    Unlike :func:`resolve_after_mutation`, this does NOT register an
    ``on_commit`` cache invalidation — the caller invalidates once after the run
    (the ``ingest_patches`` command does, as does the apply engine's caller).

    Raises ``ValueError`` for a namespace with no bulk resolver on
    *model_class*, so an unhandled relationship fails loudly instead of leaving
    its claims silently unresolved.
    """
    if not subject_ids or not field_names:
        return
    from ..models import MachineModel

    if issubclass(model_class, MachineModel):
        resolvers = _get_mm_relationship_resolvers()
        for fn in field_names:
            if fn == "media_attachment":
                _resolve_media_bulk(model_class, subject_ids)
            elif fn in resolvers:
                resolvers[fn](subject_ids=subject_ids)
            else:
                raise ValueError(
                    f"No bulk resolver for relationship {fn!r} on "
                    f"{model_class.__name__}"
                )
        return

    _resolve_non_machine_relationships_bulk(model_class, field_names, subject_ids)


def _resolve_non_machine_relationships_bulk(
    model_class: type[ClaimControlledModel],
    field_names: list[str],
    subject_ids: set[int],
) -> None:
    """Bulk relationship resolution for non-MachineModel entities.

    Reuses the same dispatch tables as :func:`_resolve_non_machine_model`, but
    invokes each resolver once for the whole subject set instead of per object
    (alias/parent resolvers resolve their whole type; custom resolvers take the
    full ``subject_ids``).
    """
    from . import _relationships
    from ._relationships import _resolve_aliases, _resolve_parents

    alias_dispatch = _get_alias_dispatch()
    parent_dispatch = _get_parent_dispatch()
    custom_dispatch = _get_custom_dispatch()

    for fn in field_names:
        if fn == "media_attachment":
            _resolve_media_bulk(model_class, subject_ids)
        elif fn in alias_dispatch and alias_dispatch[fn] is model_class:
            _resolve_aliases(model_class)
        elif fn in parent_dispatch and parent_dispatch[fn].model is model_class:
            spec = parent_dispatch[fn]
            _resolve_parents(spec.model, claim_field_prefix=spec.claim_field_prefix)
        elif fn in custom_dispatch and custom_dispatch[fn].entity_model is model_class:
            resolver = getattr(
                _relationships, custom_dispatch[fn].resolver_function_name
            )
            resolver(subject_ids=subject_ids)
        else:
            raise ValueError(
                f"No bulk resolver for relationship {fn!r} on {model_class.__name__}"
            )


def _resolve_media_bulk(
    model_class: type[ClaimControlledModel], subject_ids: set[int]
) -> None:
    """Bulk-resolve media attachments for a media-supported entity type."""
    from apps.media.models import MediaSupportedModel

    if not issubclass(model_class, MediaSupportedModel):
        return
    from django.contrib.contenttypes.models import ContentType

    from ._media import resolve_media_attachments

    ct = ContentType.objects.get_for_model(model_class)
    resolve_media_attachments(content_type_id=ct.id, subject_ids=subject_ids)
