"""Wikilink renderer/link-type registry.

Owns the registry of ``[[<entity-type>:<public-id>]]`` link types — the
shape of each addressable entity (model path, URL pattern, label/url
resolvers, custom format/metadata callbacks). Pure definitions; no
rendering, no conversion, no reference syncing.

Sibling to :mod:`apps.core.wikilinks.picker`, which owns the picker
registry. The renderer must resolve any addressable entity; the picker
only offers types the authoring UI surfaces.

Link formats:
- Public-id-based (authoring): ``[[manufacturer:burnham]]``, ``[[location:usa/il/chicago]]``
- Public-id-based (storage):   ``[[manufacturer:id:N]]``, ``[[location:id:N]]``
- ID-based (same in both):     ``[[sometype:N]]``

The authoring key is whichever model field carries URL identity — ``slug``
for most models, ``location_path`` for Location, etc. ``LinkType.public_id_field``
names that field; if it is ``None`` the type is ID-based.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.db import models


class FormatLinkCallback(Protocol):
    """Custom per-link-type renderer for ``[[type:id:N]]`` markers.

    ``obj`` is the resolved model instance (concrete type varies per link
    type; ``None`` when the target no longer exists). ``index`` is the
    1-based position of this unique ID in the rendered text; duplicate
    markers for the same ID share an index. ``base_url`` is prepended to
    relative URLs; ``plain_text`` switches to a text-only rendering.
    """

    def __call__(
        self,
        obj: Any,  # noqa: ANN401 - concrete model type varies per link type
        index: int,
        base_url: str,
        plain_text: bool,
    ) -> str: ...


class CollectMetadataCallback(Protocol):
    """Per-link-type metadata collector for ``[[type:id:N]]`` markers.

    Called once per unique resolved object by ``_render_by_id`` when
    ``metadata_out`` is provided. The returned dict is appended to
    ``metadata_out``; its shape is link-type-specific and core never
    inspects it.
    """

    def __call__(
        self,
        obj: Any,  # noqa: ANN401 - concrete model type varies per link type
        index: int,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LinkType:
    """Configuration for one rendered link type (e.g., 'manufacturer', 'title').

    Carries everything the renderer needs to resolve ``[[name:ref]]`` to a
    URL and label. Picker presentation (label, sort order, autocomplete
    config) lives separately on
    :class:`apps.core.wikilinks.PickerType` — only types offered for
    authoring need a PickerType, and not every PickerType has the same
    underlying renderer shape (citations have no URL).
    """

    # --- Identity ---
    name: str  # The string in [[name:...]]
    model_path: str  # "catalog.Manufacturer" — resolved via apps.get_model()

    # --- Public-id-based vs ID-based ---
    # If set, this type uses [[name:public_id]] authoring / [[name:id:N]]
    # storage. The value is the name of the model field carrying URL identity
    # (e.g. "slug" for most models, "location_path" for Location).
    # If None, this type is ID-based: [[name:N]] same in both formats.
    public_id_field: str | None = None

    # --- Rendering ---
    url_pattern: str = ""  # URL pattern like "/manufacturers/{public_id}"
    url_field: str = "public_id"  # model attr (field or property) to read for the URL
    label_field: str = "name"  # model field for link text (simple cases)
    get_url: Callable[[Any], str] | None = None  # override for irregular URL
    get_label: Callable[[Any], str] | None = None  # override for irregular label
    select_related: tuple[str, ...] = ()
    prefetch_related: tuple[str, ...] = ()
    # Whether this link type's markers may appear in the public export dump.
    # False for inline annotations (citations) that are stripped on export
    # regardless of public-id vs id-based form — decoupled from public_id_field
    # so the strip survives cite's flip to a public-id type.
    export_inline: bool = True
    # When set, _render_by_id() uses this instead of _format_link(). Indices are
    # assigned by unique ID in order of first appearance (duplicate markers share
    # the same index).
    format_link: FormatLinkCallback | None = None
    collect_metadata: CollectMetadataCallback | None = None

    # --- Authoring format (public-id-based types only) ---
    # Custom lookup for authoring format: (model_class, raw_values) -> {key: obj}
    # Default for public-id-based types: filter(**{public_id_field + "__in": values})
    authoring_lookup: (
        Callable[[type[models.Model], list[str]], dict[str, models.Model]] | None
    ) = None
    # Custom key derivation for storage-to-authoring: (obj) -> authoring_key
    # Default: getattr(obj, public_id_field)
    get_authoring_key: Callable[[Any], str] | None = None

    # --- Runtime toggle (evaluated at usage time, not registration time) ---
    is_enabled: Callable[[], bool] = field(default=lambda: True)

    def get_model(self) -> type[Any]:
        """Resolve the model class lazily via Django's app registry."""
        from django.apps import apps

        return apps.get_model(self.model_path)

    def resolve_url(self, obj: models.Model) -> str:
        """Resolve the URL for a linked object."""
        if self.get_url:
            return self.get_url(obj)
        value = getattr(obj, self.url_field)
        return self.url_pattern.format(**{self.url_field: value})

    def resolve_label(self, obj: models.Model) -> str:
        """Resolve the display label for a linked object."""
        if self.get_label:
            return self.get_label(obj)
        return str(getattr(obj, self.label_field, obj))


_registry: dict[str, LinkType] = {}
_patterns: dict[str, dict[str, re.Pattern[str]]] = {}


def register(link_type: LinkType) -> None:
    """Register a link type. Called from each app's AppConfig.ready()."""
    if link_type.name in _registry:
        raise ValueError(f"Link type '{link_type.name}' is already registered")
    _registry[link_type.name] = link_type
    # Compile regex patterns eagerly
    name = re.escape(link_type.name)
    if link_type.public_id_field is not None:
        _patterns[link_type.name] = {
            "storage": re.compile(rf"\[\[{name}:id:(\d+)\]\]"),
            "authoring": re.compile(rf"\[\[{name}:(?!id:)([^\]]+)\]\]"),
        }
    else:
        _patterns[link_type.name] = {
            "id": re.compile(rf"\[\[{name}:(\d+)\]\]"),
        }


def clear_registry() -> None:
    """Reset registry state. For tests only."""
    _registry.clear()
    _patterns.clear()


def get_link_type(name: str) -> LinkType | None:
    """Get a registered link type by name, or None."""
    return _registry.get(name)


def get_enabled_link_types() -> list[LinkType]:
    """Return all currently enabled link types."""
    return [lt for lt in _registry.values() if lt.is_enabled()]


def get_enabled_public_id_types() -> list[LinkType]:
    """Return enabled link types that use the public-id authoring format
    (i.e. those whose ``public_id_field`` is set; ID-based types excluded)."""
    return [lt for lt in get_enabled_link_types() if lt.public_id_field is not None]


def get_patterns(link_type: LinkType) -> dict[str, re.Pattern[str]]:
    """Get compiled regex patterns for a link type."""
    return _patterns[link_type.name]
