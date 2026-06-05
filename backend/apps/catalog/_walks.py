"""Catalog-local helpers for walking the model registry.

The four typed wrappers — ``catalog_models``, ``linkable_models``,
``wikilinkable_models``, ``alias_models`` — return concrete catalog-app
subclasses of the named abstract base. Built on Django's app registry
rather than ``__subclasses__()`` so they stay correct when abstract
intermediates are introduced between the base and its concrete descendants.

Cross-app discovery should call ``apps.get_models()`` directly; the catalog
helpers exist because most catalog walks are catalog-scoped and the
scoping documents intent.

The wrappers isolate the unavoidable ``# type: ignore[type-abstract]`` (a
known mypy limitation around abstract type parameters — see
https://github.com/python/mypy/issues/4717) inside this module rather than
spreading it across consumers, and they hand callers a strongly-typed
return so attribute access on the result needs no further casts.

Must be called after the app registry is populated (i.e. from
``AppConfig.ready()`` or later, never at module import time).
"""

from __future__ import annotations

from django.apps import apps
from django.db.models import Model

from apps.catalog.models.base import AliasModel, CatalogModel
from apps.core.autocomplete import AutocompletableModel
from apps.core.models import LinkableModel
from apps.core.wikilinks import WikilinkableModel


def _catalog_app_subclasses[T: Model](base: type[T]) -> list[type[T]]:
    """Return concrete catalog-app models that subclass ``base``.

    Filters out abstract models. ``base`` itself is excluded — callers walk
    descendants, not the base. Internal — call sites should use one of the
    typed wrappers below.
    """
    return [
        cls
        for cls in apps.get_app_config("catalog").get_models()
        if cls is not base and issubclass(cls, base) and not cls._meta.abstract
    ]


def catalog_models() -> list[type[CatalogModel]]:
    """Concrete ``CatalogModel`` descendants in the catalog app."""
    return _catalog_app_subclasses(CatalogModel)  # type: ignore[type-abstract]


def linkable_models() -> list[type[LinkableModel]]:
    """Concrete ``LinkableModel`` descendants in the catalog app."""
    return _catalog_app_subclasses(LinkableModel)  # type: ignore[type-abstract]


def wikilinkable_models() -> list[type[WikilinkableModel]]:
    """Concrete ``WikilinkableModel`` descendants in the catalog app."""
    return _catalog_app_subclasses(WikilinkableModel)  # type: ignore[type-abstract]


def autocompletable_models() -> list[type[AutocompletableModel]]:
    """Concrete ``AutocompletableModel`` descendants in the catalog app."""
    return _catalog_app_subclasses(AutocompletableModel)  # type: ignore[type-abstract]


def alias_models() -> list[type[AliasModel]]:
    """Concrete ``AliasModel`` descendants in the catalog app."""
    return _catalog_app_subclasses(AliasModel)  # type: ignore[type-abstract]
