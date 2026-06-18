"""Tests for the provenance resolve-dispatch registry.

The two entry points and per-domain registration are exercised end-to-end by
catalog's ``test_resolve_dispatch`` (per-entity) and ``test_apply`` /
``test_patches`` (bulk). These unit tests pin the registry contract itself —
fail-fast on an unregistered model, idempotent vs. conflicting registration,
and the empty-subject guard — in isolation from any domain handler.
"""

from __future__ import annotations

from collections.abc import Collection

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.catalog.models import Theme
from apps.provenance.models import ClaimControlledModel
from apps.provenance.resolution import (
    ResolveHandlers,
    _dispatch,
    register_resolve_handlers,
    resolve_after_mutation,
    resolve_entities_bulk,
)


class _Widget(ClaimControlledModel):
    """Throwaway concrete model for the proxy-normalization test.

    A direct ``ClaimControlledModel`` subclass (not ``LinkableModel`` /
    ``CatalogModel``), so it stays out of the entity registry and catalog walks.
    Never saved — the proxy test only uses the classes and an unsaved instance,
    so it needs no DB table or migration.
    """

    class Meta:
        app_label = "provenance"


class _WidgetProxy(_Widget):
    class Meta:
        app_label = "provenance"
        proxy = True


def _per_entity(
    entity: ClaimControlledModel, field_names: list[str] | None = None
) -> None: ...


def _bulk(
    model_class: type[ClaimControlledModel],
    subject_ids: set[int],
    field_names: Collection[str],
) -> None: ...


@pytest.fixture
def fresh_registry(monkeypatch):
    """Swap in an empty registry so a test's registrations don't leak.

    The real registry is populated once at ``CatalogConfig.ready()`` and shared
    process-wide; mutating it would corrupt sibling tests.
    """
    registry: dict[type[ClaimControlledModel], ResolveHandlers] = {}
    monkeypatch.setattr(_dispatch, "_resolve_handlers", registry)
    return registry


def test_bulk_dispatch_raises_for_unregistered_model(fresh_registry):
    with pytest.raises(
        ImproperlyConfigured, match="No resolve handlers registered for Theme"
    ):
        resolve_entities_bulk(Theme, {1}, frozenset())


def test_per_entity_dispatch_raises_for_unregistered_model(fresh_registry):
    # Unsaved instance — ``type(entity)`` is Theme; the raise precedes any DB use.
    with pytest.raises(
        ImproperlyConfigured, match="No resolve handlers registered for Theme"
    ):
        resolve_after_mutation(Theme(name="x", slug="x"))


def test_bulk_dispatch_noops_on_empty_subjects(fresh_registry):
    # Empty subject set returns before the registry lookup, so an unregistered
    # model is not an error when there is nothing to resolve.
    resolve_entities_bulk(Theme, set(), frozenset())


def test_register_is_idempotent_for_same_pair(fresh_registry):
    handlers = ResolveHandlers(per_entity=_per_entity, bulk=_bulk)
    register_resolve_handlers(Theme, handlers)
    register_resolve_handlers(Theme, handlers)  # no raise
    assert fresh_registry[Theme] is handlers


def test_register_conflicting_pair_raises(fresh_registry):
    def _other_bulk(
        model_class: type[ClaimControlledModel],
        subject_ids: set[int],
        field_names: Collection[str],
    ) -> None: ...

    register_resolve_handlers(
        Theme, ResolveHandlers(per_entity=_per_entity, bulk=_bulk)
    )
    with pytest.raises(ImproperlyConfigured, match="already registered"):
        register_resolve_handlers(
            Theme, ResolveHandlers(per_entity=_per_entity, bulk=_other_bulk)
        )


def test_bulk_dispatch_routes_to_registered_handler(fresh_registry):
    calls: list[tuple[type[ClaimControlledModel], set[int], frozenset[str]]] = []

    def _record(
        model_class: type[ClaimControlledModel],
        subject_ids: set[int],
        field_names: Collection[str],
    ) -> None:
        calls.append((model_class, subject_ids, frozenset(field_names)))

    register_resolve_handlers(
        Theme, ResolveHandlers(per_entity=_per_entity, bulk=_record)
    )
    resolve_entities_bulk(Theme, {1, 2}, frozenset({"theme_alias"}))

    assert calls == [(Theme, {1, 2}, frozenset({"theme_alias"}))]


def test_dispatch_keys_on_concrete_model_for_a_proxy(fresh_registry):
    # Resolution is table-level: a proxy — whose ``type()`` is the proxy class,
    # not the registered concrete model — must route to the concrete handler,
    # not miss it. (Deferred ``.only()``/``.defer()`` instances are not a
    # concern; modern Django keeps them as the concrete class.)
    per_entity_calls: list[type[ClaimControlledModel]] = []
    bulk_calls: list[type[ClaimControlledModel]] = []

    def _record_per(
        entity: ClaimControlledModel, field_names: list[str] | None = None
    ) -> None:
        per_entity_calls.append(type(entity))

    def _record_bulk(
        model_class: type[ClaimControlledModel],
        subject_ids: set[int],
        field_names: Collection[str],
    ) -> None:
        bulk_calls.append(model_class)

    register_resolve_handlers(
        _Widget, ResolveHandlers(per_entity=_record_per, bulk=_record_bulk)
    )

    # Both entry points dispatch a proxy to the concrete model's handler.
    resolve_after_mutation(_WidgetProxy(), field_names=["name"])
    resolve_entities_bulk(_WidgetProxy, {1}, frozenset())

    # Per-entity normalizes only the lookup key — the handler still receives the
    # original (proxy) instance. Bulk is called with the concrete model.
    assert per_entity_calls == [_WidgetProxy]
    assert bulk_calls == [_Widget]
