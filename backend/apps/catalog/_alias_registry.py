"""Alias-type discovery from AliasModel subclasses.

Catalog-private. Lives in its own module so ``claims.py`` and ``resolve/``
can both import it without creating a cycle between them.
"""

from __future__ import annotations

import functools
from typing import NamedTuple

from django.apps import apps
from django.db.models import Model

from apps.provenance.models import ClaimControlledModel

from ._walks import alias_models
from .models.base import AliasModel


class AliasType(NamedTuple):
    """Everything discovered about one ``AliasModel`` subclass.

    The complete, canonical record for an alias type — every consumer reads it here
    rather than re-walking the alias models:

    - ``parent_model`` / ``fk_name`` — the entity the aliases belong to and the FK on
      the alias model that points back to it (e.g. ``Theme`` / ``"theme"``). Derived
      from introspection.
    - ``claim_field`` — the claim namespace carrying alias values (``"theme_alias"``).
      Declared on the model via ``alias_claim_field``.
    - ``alias_model`` — the ``AliasModel`` subclass itself (``ThemeAlias``).
    """

    parent_model: type[ClaimControlledModel]
    claim_field: str
    alias_model: type[AliasModel]
    fk_name: str


@functools.lru_cache(maxsize=1)
def discover_alias_types() -> tuple[AliasType, ...]:
    """Return an ``AliasType`` per ``AliasModel`` subclass.

    Must be called after Django's models are loaded. The
    ``@functools.lru_cache(maxsize=1)`` decorator pins the first result,
    so this is both a discovery walk and a process-lifetime cache.

    Subclasses are guaranteed to declare ``alias_claim_field`` by
    ``AliasModel.__init_subclass__`` — the validation lives at class
    creation, not here.
    """
    apps.check_models_ready()

    result: list[AliasType] = []
    for alias_cls in alias_models():
        # Each AliasModel subclass has exactly one FK to its parent model.
        fks = [
            f
            for f in alias_cls._meta.get_fields()
            if hasattr(f, "related_model") and f.many_to_one
        ]
        if len(fks) != 1:
            raise RuntimeError(
                f"{alias_cls.__name__} has {len(fks)} ForeignKeys; expected exactly 1"
            )
        parent_model = fks[0].related_model
        if parent_model is None or isinstance(parent_model, str):
            raise RuntimeError(f"{alias_cls.__name__} FK has no related model")
        if not issubclass(parent_model, ClaimControlledModel):
            raise RuntimeError(
                f"{alias_cls.__name__} parent {parent_model.__name__} "
                "is not a ClaimControlledModel subclass"
            )
        result.append(
            AliasType(
                parent_model=parent_model,
                claim_field=alias_cls.alias_claim_field,
                alias_model=alias_cls,
                fk_name=fks[0].name,
            )
        )

    return tuple(sorted(result, key=lambda at: at.claim_field))


@functools.lru_cache(maxsize=1)
def _alias_types_by_parent() -> dict[type[Model], AliasType]:
    return {at.parent_model: at for at in discover_alias_types()}


def alias_type_for(parent_model: type[Model]) -> AliasType | None:
    """The ``AliasType`` for *parent_model*, or ``None`` if it has no aliases — the
    canonical parent → record lookup both alias resolution and the listing ``q`` fold
    read, so neither re-derives the alias model / FK from the model."""
    return _alias_types_by_parent().get(parent_model)
