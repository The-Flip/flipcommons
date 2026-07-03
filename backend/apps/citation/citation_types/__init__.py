"""Citation-type and scheme plugins, behind one registry.

Public surface of the plugin system: consumers import from this package, not
from individual plugin modules. See ``docs/plans/citations/VideoCitations.md``
for the architecture and ``base.py`` for the contracts.
"""

from apps.citation.citation_types.base import (
    CitationTypeSpec,
    RootSeed,
    SchemeMatch,
    SchemeSpec,
    SourceType,
)
from apps.citation.citation_types.registry import (
    CITATION_TYPE_SPECS,
    SCHEME_SPECS,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
)

__all__ = [
    "CITATION_TYPE_SPECS",
    "SCHEME_SPECS",
    "CitationTypeSpec",
    "RootSeed",
    "SchemeMatch",
    "SchemeSpec",
    "SourceType",
    "citation_type_spec",
    "identifier_key_choices",
    "identifier_key_values",
]
