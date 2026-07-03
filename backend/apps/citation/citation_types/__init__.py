"""Citation-type and scheme plugins, behind one registry.

Public surface of the plugin system: consumers import from this package, not
from individual plugin modules. See ``docs/plans/citations/VideoCitations.md``
for the architecture and ``base.py`` for the contracts.
"""

from apps.citation.citation_types.base import (
    CitationSourceTypeValue,
    CitationTypeSpec,
    LocatorContract,
    RootSeed,
    SchemeKey,
    SchemeMatch,
    SchemeSpec,
    SourceType,
    StartSeconds,
    citation_source_type,
)
from apps.citation.citation_types.registry import (
    CITATION_TYPE_SPECS,
    SCHEME_SPECS,
    SchemeBinding,
    SchemeChoice,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
    scheme_bindings,
)

__all__ = [
    "CITATION_TYPE_SPECS",
    "SCHEME_SPECS",
    "CitationTypeSpec",
    "LocatorContract",
    "RootSeed",
    "SchemeBinding",
    "SchemeChoice",
    "SchemeKey",
    "SchemeMatch",
    "SchemeSpec",
    "SourceType",
    "StartSeconds",
    "CitationSourceTypeValue",
    "citation_type_spec",
    "identifier_key_choices",
    "identifier_key_values",
    "scheme_bindings",
    "citation_source_type",
]
