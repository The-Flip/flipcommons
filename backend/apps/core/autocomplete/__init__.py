"""Generic, model-driven autocomplete subsystem.

- :class:`AutocompletableModel` — abstract base a model inherits to be
  searchable from typeahead controls.
- :class:`AutocompleteType` / :func:`register_autocomplete` — the cross-app
  registry each app populates from its ``AppConfig.ready()``.
- :func:`run_autocomplete` — the shared diacritic-folding, alias-aware search
  engine every consumer runs through (the wikilink ``[[`` picker today).
"""

from apps.core.autocomplete.models import AutocompletableModel
from apps.core.autocomplete.registry import (
    AUTOCOMPLETE_RESULT_LIMIT,
    AutocompleteRow,
    AutocompleteType,
    clear_registry,
    get_autocomplete_type,
    get_autocomplete_types,
    register_autocomplete,
    run_autocomplete,
)

__all__ = [
    "AUTOCOMPLETE_RESULT_LIMIT",
    "AutocompletableModel",
    "AutocompleteRow",
    "AutocompleteType",
    "clear_registry",
    "get_autocomplete_type",
    "get_autocomplete_types",
    "register_autocomplete",
    "run_autocomplete",
]
