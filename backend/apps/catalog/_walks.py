"""Catalog-scoped wrappers over the engine's generic model-registry walk.

The five typed wrappers — ``catalog_models``, ``linkable_models``,
``wikilinkable_models``, ``autocompletable_models``, ``alias_models`` — return
concrete catalog-app subclasses of the named abstract base. They scope
``engine.walks.app_subclasses`` to the ``"catalog"`` app, document intent, and
isolate the unavoidable ``# type: ignore[type-abstract]`` (a known mypy
limitation around abstract type parameters — see
https://github.com/python/mypy/issues/4717) inside this module rather than
spreading it across consumers, handing callers a strongly-typed return so
attribute access needs no further casts.

Cross-app discovery should call ``apps.get_models()`` directly; these helpers
exist because most catalog walks are catalog-scoped.

Must be called after the app registry is populated (i.e. from
``AppConfig.ready()`` or later, never at module import time).
"""

from __future__ import annotations

from apps.core.autocomplete import AutocompletableModel
from apps.core.models import LinkableModel
from apps.core.wikilinks import WikilinkableModel

from .engine.walks import app_subclasses
from .models.base import AliasModel, CatalogModel


def catalog_models() -> list[type[CatalogModel]]:
    """Concrete ``CatalogModel`` descendants in the catalog app."""
    return app_subclasses("catalog", CatalogModel)  # type: ignore[type-abstract]


def linkable_models() -> list[type[LinkableModel]]:
    """Concrete ``LinkableModel`` descendants in the catalog app."""
    return app_subclasses("catalog", LinkableModel)  # type: ignore[type-abstract]


def wikilinkable_models() -> list[type[WikilinkableModel]]:
    """Concrete ``WikilinkableModel`` descendants in the catalog app."""
    return app_subclasses("catalog", WikilinkableModel)  # type: ignore[type-abstract]


def autocompletable_models() -> list[type[AutocompletableModel]]:
    """Concrete ``AutocompletableModel`` descendants in the catalog app."""
    return app_subclasses("catalog", AutocompletableModel)  # type: ignore[type-abstract]


def alias_models() -> list[type[AliasModel]]:
    """Concrete ``AliasModel`` descendants in the catalog app."""
    return app_subclasses("catalog", AliasModel)  # type: ignore[type-abstract]
