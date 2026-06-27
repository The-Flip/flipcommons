"""The resolve-dispatch registry and its two entry points.

Resolution (materializing denormalized fields and through-tables from claims)
is the domain's job and stays in the domain app. But three callers must reach
it without importing the domain: the interactive write path (``claim_edit``'s
``execute_*``), the bulk pipeline (``claim_ingest``'s apply engine) and
``revert``. They call the two dispatch entries here instead.

Each domain registers a :class:`ResolveHandlers` pair per concrete
claim-controlled model at ``AppConfig.ready()`` (catalog does this for its 21
models; a future baseball/medicine domain registers its own). The dispatch
entries look the pair up by model class and call the matching half. A model
with no registered handlers raises :class:`ImproperlyConfigured` — fail-fast,
so a domain that forgets to register is caught loudly rather than silently
skipping resolution.

This module imports no domain symbol: the concrete resolvers and their cache
invalidation live in the domain app. Mirrors the relationship-schema registry
in :mod:`apps.provenance.validation`.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import NamedTuple, Protocol

from django.core.exceptions import ImproperlyConfigured

from apps.core.types import ClaimFieldName, ClaimSubjectId
from apps.provenance.models import ClaimControlledModel


class PerEntityResolver(Protocol):
    """Re-resolve one mutated entity in place.

    Accepts **any** changed field name — scalar and relationship both. The
    handler always re-resolves scalars and filters the relationship subset
    itself, so callers pass the full set of changed ``field_name`` values
    (``None`` means "all applicable"). The handler owns its cache invalidation.
    """

    def __call__(
        self,
        entity: ClaimControlledModel,
        field_names: list[ClaimFieldName] | None = None,
    ) -> None: ...


class BulkResolver(Protocol):
    """Batch re-resolve many subjects of one model class in one pass.

    ``field_names`` are **relationship namespaces only** — the scalar half
    re-resolves every field regardless, and the relationship half rejects a
    non-relationship name. Does not invalidate caches (the bulk caller does so
    once after the whole run).
    """

    def __call__(
        self,
        model_class: type[ClaimControlledModel],
        subject_ids: set[ClaimSubjectId],
        field_names: Collection[ClaimFieldName],
    ) -> None: ...


class ResolveHandlers(NamedTuple):
    """The per-entity and bulk resolvers registered for one model class."""

    per_entity: PerEntityResolver
    bulk: BulkResolver


_resolve_handlers: dict[type[ClaimControlledModel], ResolveHandlers] = {}


def register_resolve_handlers(
    model_class: type[ClaimControlledModel], handlers: ResolveHandlers
) -> None:
    """Register the resolve handlers for a concrete model.

    Idempotent; re-registering the same pair is a no-op, a conflicting pair
    raises. Called from the owning domain's ``AppConfig.ready()``.
    """
    existing = _resolve_handlers.get(model_class)
    if existing is not None and existing != handlers:
        raise ImproperlyConfigured(
            f"resolve handlers already registered for {model_class.__name__} "
            f"with a different pair"
        )
    _resolve_handlers[model_class] = handlers


def _concrete(model_class: type[ClaimControlledModel]) -> type[ClaimControlledModel]:
    """Normalize a model class to its concrete model — the registry key.

    Registration keys on concrete models (the catalog-scoped walk yields them),
    and resolution is a table-level operation, so a proxy must route to the
    concrete model's handler, not miss it. ``concrete_model`` is the model
    itself for a normal concrete class (a no-op), the base for a proxy; for any
    ``ClaimControlledModel`` subclass it is necessarily claim-controlled, which
    the ``issubclass`` check both verifies at runtime and uses to narrow
    django-stubs' ``type[Model]`` to the bound — no unchecked ``cast``.
    """
    concrete = model_class._meta.concrete_model
    assert concrete is not None  # always set for a concrete/proxy model
    assert issubclass(concrete, ClaimControlledModel)
    return concrete


def _handlers_for(concrete_model: type[ClaimControlledModel]) -> ResolveHandlers:
    handlers = _resolve_handlers.get(concrete_model)
    if handlers is None:
        raise ImproperlyConfigured(
            f"No resolve handlers registered for {concrete_model.__name__}. "
            f"The owning app must register them in AppConfig.ready()."
        )
    return handlers


def resolve_after_mutation(
    entity: ClaimControlledModel, field_names: list[ClaimFieldName] | None = None
) -> None:
    """Per-entity dispatch: re-resolve a single mutated entity.

    Call inside a ``transaction.atomic()`` block after creating, deactivating
    or modifying claims. Routes to the registered :class:`PerEntityResolver`
    for the entity's concrete model; the handler runs resolution synchronously
    inside the caller's transaction and schedules cache invalidation.
    """
    _handlers_for(_concrete(type(entity))).per_entity(entity, field_names)


def resolve_entities_bulk(
    model_class: type[ClaimControlledModel],
    subject_ids: set[ClaimSubjectId],
    field_names: Collection[ClaimFieldName],
) -> None:
    """Bulk dispatch: re-resolve many subjects of one model class in one pass.

    Routes to the registered :class:`BulkResolver`, keyed (and called) on the
    concrete model. ``field_names`` are the changed relationship namespaces
    (empty for a scalar-only change — the handler still re-resolves scalars).
    An empty ``subject_ids`` is a no-op (nothing to resolve), returning before
    the registry lookup.
    """
    if not subject_ids:
        return
    concrete = _concrete(model_class)
    _handlers_for(concrete).bulk(concrete, subject_ids, field_names)
