"""Public entity_type → linkable model class resolution.

Every linkable entity declares a hyphenated canonical public identifier via
``LinkableModel.entity_type``. This module is the single adapter from that
public string to the concrete model class. Callers that need Django's
concatenated ``_meta.model_name`` or a ContentType use the returned class
directly.

Unknown (or concatenated / Django-internal) entity_type strings raise
``ValueError``; callers translate to HTTP 404.

See ``docs/EntityNaming.md`` for the naming rule (hyphenated singular; the
frontend route segment is its plural) and the generated frontend mirror at
``frontend/src/lib/entities/entity-meta.ts``.
"""

from __future__ import annotations

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured

from apps.core.models import LinkableModel

_ENTITY_TYPE_MAP: dict[str, type[LinkableModel]] | None = None


def _build_map() -> dict[str, type[LinkableModel]]:
    # Ensure all apps are loaded so every LinkableModel subclass is imported.
    apps.check_apps_ready()
    result: dict[str, type[LinkableModel]] = {}
    for cls in apps.get_models():
        if not issubclass(cls, LinkableModel) or cls._meta.abstract:
            continue
        key = cls.entity_type
        if key in result:
            raise ImproperlyConfigured(
                f"Duplicate entity_type {key!r}: "
                f"{result[key].__name__} and {cls.__name__}"
            )
        result[key] = cls
    return result


def all_linkable_models() -> list[type[LinkableModel]]:
    """Every concrete ``LinkableModel`` class, in registry order.

    Cross-app: walks the full app registry (see ``_build_map``), so it spans
    catalog and any other app whose models subclass ``LinkableModel``. This is
    the source set for ``export_entity_meta`` — the generated frontend entity
    registry mirrors exactly these classes. Because it is registry-driven, a new
    linkable entity (e.g. a future SSR ``User``) joins automatically by
    subclassing ``LinkableModel`` and declaring its ``entity_type``.

    No ordering is promised; callers that need a stable order (e.g. codegen)
    sort for themselves.
    """
    global _ENTITY_TYPE_MAP
    if _ENTITY_TYPE_MAP is None:
        _ENTITY_TYPE_MAP = _build_map()
    return list(_ENTITY_TYPE_MAP.values())


def get_linkable_model(entity_type: str) -> type[LinkableModel]:
    """Return the linkable model class for a canonical entity_type string.

    Raises ``ValueError`` if the entity_type is unknown — including
    Django-internal concatenated forms like ``'corporateentity'`` or
    ``'machinemodel'``.
    """
    global _ENTITY_TYPE_MAP
    if _ENTITY_TYPE_MAP is None:
        _ENTITY_TYPE_MAP = _build_map()
    try:
        return _ENTITY_TYPE_MAP[entity_type]
    except KeyError:
        raise ValueError(f"Unknown entity type: {entity_type}") from None
