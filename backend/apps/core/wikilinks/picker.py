"""Wikilink picker registry — the type-picker the markdown editor surfaces.

Sibling to :mod:`apps.core.wikilinks.types`, which owns the *renderer* registry
(every URL-addressable entity that ``[[<entity-type>:<public-id>]]`` can resolve to). This
module owns the *picker* registry — the strict subset of types the authoring
UI offers when a user types ``[[``.

Why a separate registry: the renderer needs to resolve any addressable entity
(``LinkableModel``); the picker only offers types we want users to author
against (``WikilinkableModel`` plus a few special cases like citations).

The picker carries only *menu* presentation — label, description, sort order
and flow. The *search* behind a standard-flow entry comes from the
:mod:`apps.core.autocomplete` registry under the same ``name``: the picker
endpoint delegates to :func:`apps.core.autocomplete.run_autocomplete`. A
``flow="custom"`` entry (citations) drives its own frontend flow and has no
autocomplete type behind it.

The ``register_picker`` / ``get_picker_type`` / ``get_picker_types`` helpers
are re-exported by :mod:`apps.core.wikilinks` (the package ``__init__``);
prefer that import path from outside this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

FLOWS = ("standard", "custom")


@dataclass(frozen=True)
class PickerType:
    """One entry in the wikilink autocomplete picker — menu presentation only.

    For ``flow="standard"`` types (the common case), the picker endpoint runs
    the shared autocomplete query registered under the same ``name`` (an
    :class:`~apps.core.autocomplete.AutocompleteType`). For ``flow="custom"``
    types (citations), the frontend drives the flow end-to-end and no
    autocomplete type is registered.
    """

    name: str  # Registry key — matches the AutocompleteType / LinkType name.
    label: str
    description: str
    sort_order: int = 100
    flow: str = "standard"

    # --- Runtime toggle (evaluated at usage time, not registration time) ---
    is_enabled: Callable[[], bool] = field(default=lambda: True)


_registry: dict[str, PickerType] = {}


def register_picker(picker_type: PickerType) -> None:
    """Register a picker type. Called from each app's ``AppConfig.ready()``."""
    if picker_type.name in _registry:
        raise ValueError(f"Picker type '{picker_type.name}' is already registered")
    if picker_type.flow not in FLOWS:
        raise ValueError(
            f"Picker type '{picker_type.name}': flow must be one of "
            f"{FLOWS}, got {picker_type.flow!r}"
        )
    _registry[picker_type.name] = picker_type


def clear_registry() -> None:
    """Reset registry state. For tests only."""
    _registry.clear()


def get_picker_type(name: str) -> PickerType | None:
    """Get a registered picker type by name, or None."""
    return _registry.get(name)


def get_picker_types() -> list[dict[str, str]]:
    """Return enabled picker types in display order, for the type-picker API."""
    types = sorted(
        (pt for pt in _registry.values() if pt.is_enabled()),
        key=lambda pt: pt.sort_order,
    )
    return [
        {
            "name": pt.name,
            "label": pt.label,
            "description": pt.description,
            "flow": pt.flow,
        }
        for pt in types
    ]
