"""Alias-type registry — neutral over whatever ``AliasModel`` subclasses it's handed.

The engine never walks the model registry itself: scoping a walk to one app
would force it to name the domain, the one leak the
``catalog.engine ⊄ catalog-domain`` contract can't catch (a string, not an
import). Instead the domain app pushes its concrete ``AliasModel`` subclasses
down here once at startup via :func:`register_alias_types` — the same inversion
catalog uses to feed ``core``'s wikilink / autocomplete registries from its
``AppConfig.ready``.

After registration, :func:`discover_alias_types` and :func:`alias_type_for` are
the canonical readers — every consumer reads the ``AliasType`` here rather than
re-deriving the alias model / FK from the parent model.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from django.db.models import Model

from apps.provenance.models import ClaimControlledModel

from .models import AliasModel


class AliasType(NamedTuple):
    """Everything discovered about one ``AliasModel`` subclass.

    The complete, canonical record for an alias type:

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


_ALIAS_TYPES: tuple[AliasType, ...] = ()
_BY_PARENT: dict[type[Model], AliasType] = {}


def register_alias_types(alias_classes: Iterable[type[AliasModel]]) -> None:
    """Discover and register an ``AliasType`` per given ``AliasModel`` subclass.

    Called once from the domain app's ``AppConfig.ready`` with its concrete
    ``AliasModel`` subclasses. Idempotent — a second call replaces the registry,
    so re-running ``ready`` (or a test re-registering) stays safe.

    Subclasses are guaranteed to declare ``alias_claim_field`` by
    ``AliasModel.__init_subclass__`` — the validation lives at class creation,
    not here.
    """
    result: list[AliasType] = []
    for alias_cls in alias_classes:
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

    global _ALIAS_TYPES, _BY_PARENT
    _ALIAS_TYPES = tuple(sorted(result, key=lambda at: at.claim_field))
    _BY_PARENT = {at.parent_model: at for at in _ALIAS_TYPES}


def discover_alias_types() -> tuple[AliasType, ...]:
    """Return the registered ``AliasType`` per alias model, sorted by claim field.

    Empty until :func:`register_alias_types` runs at startup.
    """
    return _ALIAS_TYPES


def alias_type_for(parent_model: type[Model]) -> AliasType | None:
    """The ``AliasType`` for *parent_model*, or ``None`` if it has no aliases — the
    canonical parent → record lookup both alias resolution and the listing ``q`` fold
    read, so neither re-derives the alias model / FK from the model."""
    return _BY_PARENT.get(parent_model)
