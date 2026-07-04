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
    SchemeRecognition,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
    is_known_scheme,
    known_scheme_keys,
    normalize_scheme_identifier,
    recognize_scheme,
    scheme_bindings,
    scheme_root_seed,
    scheme_source_type,
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
    "SchemeRecognition",
    "SchemeSpec",
    "SourceType",
    "StartSeconds",
    "CitationSourceTypeValue",
    "citation_type_spec",
    "identifier_key_choices",
    "identifier_key_values",
    "is_known_scheme",
    "known_scheme_keys",
    "normalize_scheme_identifier",
    "recognize_scheme",
    "scheme_bindings",
    "scheme_root_seed",
    "scheme_source_type",
    "citation_source_type",
]
