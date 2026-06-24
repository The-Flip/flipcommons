"""backing_model → ActorModel subclass resolution.

The single adapter from an ``Actor.backing_model`` string (Django's
``_meta.model_name``, e.g. ``"user"`` / ``"source"``) to the concrete backing
class, plus the per-type ``is_machine`` derivation. Registry-driven: a new
actor type joins automatically by subclassing ``ActorModel`` — no edit here.

Walks the app registry rather than importing satellites, preserving the
import-linter spine (``apps.actors`` never imports ``accounts`` / ``provenance``).
"""

from __future__ import annotations

from django.apps import apps

from .models import ActorModel

type BackingModelName = str
"""An ``Actor.backing_model`` value — Django's ``_meta.model_name`` of a
concrete ``ActorModel`` subclass (e.g. ``"user"``, ``"source"``). Not any
string: a registry key, not a slug/entity_type."""

_BACKING_MAP: dict[BackingModelName, type[ActorModel]] | None = None


def _build_map() -> dict[BackingModelName, type[ActorModel]]:
    # Walks apps.get_models() (installed, concrete, registered) — the right set
    # for runtime resolution of real actors. The system check (checks.py) walks
    # __subclasses__() instead, to validate every subclass's shape incl. stubs.
    # Same intentional split as core.entity_types vs core.checks; do not unify.
    apps.check_apps_ready()
    result: dict[BackingModelName, type[ActorModel]] = {}
    for cls in apps.get_models():
        if not issubclass(cls, ActorModel) or cls._meta.abstract:
            continue
        model_name = cls._meta.model_name
        if model_name is None:  # never None for a concrete model; narrows for mypy
            continue
        result[model_name] = cls
    return result


def actor_backing_models() -> dict[BackingModelName, type[ActorModel]]:
    """Map of ``backing_model`` → concrete ``ActorModel`` subclass.

    Cached after first build. Callers must not mutate the result.
    """
    global _BACKING_MAP
    if _BACKING_MAP is None:
        _BACKING_MAP = _build_map()
    return dict(_BACKING_MAP)


def backing_model_class(backing_model: BackingModelName) -> type[ActorModel]:
    """Resolve a ``backing_model`` string to its concrete class.

    Raises ``ValueError`` for an unregistered value.
    """
    try:
        return actor_backing_models()[backing_model]
    except KeyError:
        raise ValueError(f"Unknown backing_model: {backing_model!r}") from None


def is_machine_actor(backing_model: BackingModelName) -> bool:
    """Whether the given ``backing_model`` is a machine actor type."""
    return backing_model_class(backing_model).is_machine
