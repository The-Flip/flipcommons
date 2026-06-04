"""Autocomplete type registry + search engine.

A cross-app, model-driven registry of "how to search a type" for typeahead
controls. Each app registers its autocompletable types from its own
``AppConfig.ready()``; core owns the registry and the shared
:func:`run_autocomplete` engine, importing no peer app.

An :class:`AutocompleteType` holds only the *search* config (model, fields,
ordering); identity and labels come from the model's
:class:`~apps.core.autocomplete.AutocompletableModel` interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from django.db import connection
from django.db.models import Q

from apps.core.autocomplete.models import AutocompletableModel
from apps.core.search import fold

# Max rows any autocomplete query returns. Small by design: a typeahead shows a
# short list, and an empty query falls back to the top-N rather than the table.
AUTOCOMPLETE_RESULT_LIMIT = 20


class AutocompleteRow(NamedTuple):
    """One autocomplete result. ``value`` is the identity string the consumer
    saves (a slug for catalog entities); ``sublabel`` disambiguates rows that
    share a ``label`` (e.g. same-named titles)."""

    value: str
    label: str
    sublabel: str | None


@dataclass(frozen=True)
class AutocompleteType:
    """One registered autocompletable type — the *engine* config only.

    ``name`` is the registry key the consumer passes (``manufacturer``,
    ``title``, …). The rest mirror the model's :class:`AutocompletableModel`
    contract; identity (``value``/``label``) and ``sublabel`` are the model's
    concern, read off each instance at serialize time — not stored here.
    """

    name: str
    model_path: str  # "catalog.Manufacturer" — resolved via apps.get_model()
    search_fields: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ()
    select_related: tuple[str, ...] = ()

    def get_model(self) -> type[AutocompletableModel]:
        """Resolve the model class lazily via Django's app registry.

        The ``issubclass`` assert both verifies the registration invariant
        (every registered ``model_path`` resolves to an ``AutocompletableModel``
        — a bad path fails loudly here, at first use) and narrows the
        ``apps.get_model`` result so the engine stays fully typed downstream.
        """
        from django.apps import apps

        model = apps.get_model(self.model_path)
        assert issubclass(model, AutocompletableModel)
        return model


_registry: dict[str, AutocompleteType] = {}


def register_autocomplete(autocomplete_type: AutocompleteType) -> None:
    """Register an autocomplete type. Called from each app's ``AppConfig.ready()``."""
    if autocomplete_type.name in _registry:
        raise ValueError(
            f"Autocomplete type '{autocomplete_type.name}' is already registered"
        )
    _registry[autocomplete_type.name] = autocomplete_type


def clear_registry() -> None:
    """Reset registry state. For tests only."""
    _registry.clear()


def get_autocomplete_type(name: str) -> AutocompleteType | None:
    """Get a registered autocomplete type by name, or None."""
    return _registry.get(name)


def get_autocomplete_types() -> list[AutocompleteType]:
    """Return all registered autocomplete types."""
    return list(_registry.values())


def _search_q(search_fields: tuple[str, ...], q: str) -> Q:
    """ORed diacritic-folded ``icontains`` over *search_fields* for term *q*.

    Postgres: ``UNACCENT(path) ILIKE %fold(q)%`` per path — both sides folded,
    so accents match either direction. SQLite (dev/CI): plain ``icontains`` —
    no folding, the same dev/prod gap the listing pages share. Works for direct
    and relation paths alike; the caller ``.distinct()``\\ s to absorb
    relation-join row multiplication.
    """
    is_postgres = connection.vendor == "postgresql"
    folded = fold(q)
    q_filter = Q()
    for path in search_fields:
        if is_postgres:
            q_filter |= Q(**{f"{path}__unaccent__icontains": folded})
        else:
            q_filter |= Q(**{f"{path}__icontains": q})
    return q_filter


def _serialize(obj: AutocompletableModel) -> AutocompleteRow:
    """Serialize one row via the ``AutocompletableModel`` interface."""
    return AutocompleteRow(
        value=obj.public_id,
        label=obj.label,
        sublabel=obj.autocomplete_sublabel(),
    )


def run_autocomplete(
    name: str, q: str, *, limit: int = AUTOCOMPLETE_RESULT_LIMIT
) -> list[AutocompleteRow]:
    """Search a registered type for *q*, returning at most *limit* rows.

    Resolves the type → its model's ``autocomplete_queryset()`` (default
    ``.active()``) → diacritic-folded OR over ``search_fields`` (``.distinct()``
    to absorb relation-join multiplication) → ``ordering`` → ``[:limit]`` →
    serialize. An empty *q* skips the filter, yielding the ordered top-N so a
    freshly-focused control isn't blank.

    Raises ``KeyError`` if *name* isn't registered — callers that accept
    untrusted input (the endpoint, the ``[[`` picker) gate on
    :func:`get_autocomplete_type` first and surface a 400.
    """
    autocomplete_type = _registry[name]
    model = autocomplete_type.get_model()

    qs = model.autocomplete_queryset()
    if autocomplete_type.select_related:
        qs = qs.select_related(*autocomplete_type.select_related)
    if q and autocomplete_type.search_fields:
        qs = qs.filter(_search_q(autocomplete_type.search_fields, q)).distinct()
    if autocomplete_type.ordering:
        qs = qs.order_by(*autocomplete_type.ordering)

    return [_serialize(obj) for obj in qs[:limit]]
