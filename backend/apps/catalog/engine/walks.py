"""Generic helper for walking one app's concrete model subclasses.

Domain-neutral: ``app_subclasses`` takes the app label as a parameter and
names no concrete domain. The catalog-side typed wrappers in
``catalog._walks`` supply ``"catalog"`` and isolate the unavoidable
``# type: ignore[type-abstract]`` (a known mypy limitation around abstract
type parameters — see https://github.com/python/mypy/issues/4717).

Built on Django's app registry rather than ``__subclasses__()`` so results
stay correct when abstract intermediates are introduced between the base and
its concrete descendants.

Must be called after the app registry is populated (i.e. from
``AppConfig.ready()`` or later, never at module import time).
"""

from __future__ import annotations

from django.apps import apps
from django.db.models import Model


def app_subclasses[T: Model](app_label: str, base: type[T]) -> list[type[T]]:
    """Return concrete models in *app_label* that subclass *base*.

    Filters out abstract models. ``base`` itself is excluded — callers walk
    descendants, not the base.
    """
    return [
        cls
        for cls in apps.get_app_config(app_label).get_models()
        if cls is not base and issubclass(cls, base) and not cls._meta.abstract
    ]
