"""System check for the ActorModel registry contract.

Validates the *class shape* of every concrete ``ActorModel`` subclass — it is
deliberately DB-free (no ``Actor`` row queries), because system checks run
around ``migrate`` on a possibly-tableless database. Mirrors
``apps.core.checks.check_linkable_models`` (which walks classes, not rows).

Row-level integrity ("every ``Actor.backing_model`` is registered") is
guaranteed structurally — the only write path is ``ActorModel.save()``, which
always sets ``self._meta.model_name`` — and is asserted by a test, not here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.apps.config import AppConfig
from django.core.checks import CheckMessage, Error, Tags, register

from .models import ActorModel


@register(Tags.models)
def check_actor_models(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,  # noqa: ANN401  # Django check-framework signature
) -> list[CheckMessage]:
    """Validate every concrete ``ActorModel`` subclass.

    Each must declare ``is_machine`` as a ``bool`` and override both resolution
    hooks (``actor_priority``, ``actor_resolution_status``); otherwise minting
    would raise ``NotImplementedError`` or read a missing attribute at runtime.
    """
    _ = app_configs, kwargs
    errors: list[CheckMessage] = []
    visited: set[type] = set()

    # Walks __subclasses__() (every subclass, incl. abstract intermediates and
    # test stubs) rather than apps.get_models() (installed/concrete only, which
    # the registry uses): a shape check must catch a malformed subclass even if
    # unregistered. Same intentional split as core.checks vs core.entity_types.
    def walk(cls: type[ActorModel]) -> None:
        for subclass in cls.__subclasses__():
            if subclass in visited:
                continue
            visited.add(subclass)
            walk(subclass)
            meta = getattr(subclass, "_meta", None)
            if meta is None or meta.abstract:
                continue
            errors.extend(_check_one(subclass))

    # ``ActorModel`` is abstract; ``__subclasses__()`` is the documented walk
    # entry point (same pattern as check_linkable_models).
    walk(ActorModel)  # type: ignore[type-abstract]
    return errors


def _check_one(model: type) -> list[CheckMessage]:
    # Typed ``type`` (not ``type[ActorModel]``) so the body's duck-typed
    # ``getattr`` access lets tests pass synthetic stand-ins to exercise each
    # error branch. Production callers always pass a real ActorModel subclass
    # from ``__subclasses__()``. Mirrors apps.core.checks._check_one.
    errors: list[CheckMessage] = []

    is_machine = getattr(model, "is_machine", None)
    if not isinstance(is_machine, bool):
        errors.append(
            Error(
                f"{model.__name__} inherits ActorModel but does not declare "
                "``is_machine`` as a bool.",
                obj=model,
                id="actors.E001",
            )
        )

    for hook in ("actor_priority", "actor_resolution_status"):
        if getattr(model, hook) is getattr(ActorModel, hook):
            errors.append(
                Error(
                    f"{model.__name__} inherits ActorModel but does not override "
                    f"``{hook}`` (the base raises NotImplementedError).",
                    obj=model,
                    id="actors.E002",
                )
            )

    return errors
