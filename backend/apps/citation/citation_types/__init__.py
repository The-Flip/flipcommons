"""The two citation plugin frameworks — types and schemes — behind one registry.

The package root is the plugin systems' public surface. Two plugin axes live
here, each with its own author module and its own framework module, meeting
only at the registry's composition weaves (see
``docs/plans/citations/CitationPluginSystem.md``):

- **Citation types** (book, magazine, web, video — first-party, allowed real
  programming): authors declare in ``citation_type_specs`` and write their
  grammar code in their type module; the framework runs it via
  ``citation_type_driver``.
- **Citation schemes** (ipdb, youtube, … — third-party, pure configuration):
  authors declare in ``citation_scheme_specs`` and nothing else; the
  framework compiles and runs the declarations via
  ``citation_scheme_driver``.

Import-linter contracts make the walls structural: plugin modules import
only declarations, never a framework module, and scheme authoring never
sees type authoring. External customers — code using the citation system
without knowing a plugin exists — import the named registry accessors and
never read a spec's fields. The framework-channel exports at the end of
``__all__`` are consumed only by the framework's own DB operations
(``extractors``/``deep_links``/``locators``), the codegen commands and
tests.
"""

from apps.citation.citation_types.citation_scheme_driver import SchemeDriver
from apps.citation.citation_types.citation_scheme_specs import (
    SchemeKey,
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    StartSecondsSource,
    UrlShape,
)
from apps.citation.citation_types.citation_type_driver import CitationTypeDriver
from apps.citation.citation_types.citation_type_specs import (
    CitationTypeSpec,
    LocatorContract,
)
from apps.citation.citation_types.registry import (
    CITATION_TYPE_DRIVERS,
    CITATION_TYPE_SPECS,
    SCHEME_DRIVERS,
    SCHEME_SPECS,
    SchemeBinding,
    SchemeChoice,
    SchemeRecognition,
    citation_type_driver,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
    is_known_scheme,
    known_scheme_keys,
    normalize_scheme_identifier,
    recognize_scheme,
    scheme_bindings,
    scheme_canonical_url,
    scheme_deep_link,
    scheme_root_citation_source_info,
    scheme_source_type,
    scheme_start_seconds_hint,
    slug_addressed_source_types,
)
from apps.citation.citation_types.vocabulary import (
    ISBN_CITE_PREFIX,
    CitationSourceTypeValue,
    SourceType,
    StartSeconds,
    citation_source_type,
)

__all__ = [
    # ----- Scheme-author surface: pure configuration, nothing else -----
    "SchemeSpec",
    "SchemeRootCitationSourceInfo",
    "UrlShape",
    "StartSecondsSource",
    # ----- Type-author surface: declarations for first-party type code -----
    "CitationTypeSpec",
    "LocatorContract",
    # ----- External-customer surface: named queries, never spec fields -----
    "citation_type_spec",
    "recognize_scheme",
    "SchemeRecognition",
    "scheme_source_type",
    "normalize_scheme_identifier",
    "scheme_canonical_url",
    "scheme_deep_link",
    "scheme_start_seconds_hint",
    "scheme_root_citation_source_info",
    "is_known_scheme",
    "known_scheme_keys",
    "citation_source_type",
    # ----- Shared vocabulary: semantic aliases and the type enum -----
    "SourceType",
    "CitationSourceTypeValue",
    "SchemeKey",
    "StartSeconds",
    "ISBN_CITE_PREFIX",
    # ----- Framework channel: constraint derivation (models), the drivers
    # and raw spec mappings (extractors/deep_links/locators, codegen, tests
    # only) -----
    "identifier_key_values",
    "identifier_key_choices",
    "SchemeChoice",
    "scheme_bindings",
    "SchemeBinding",
    "slug_addressed_source_types",
    "CITATION_TYPE_SPECS",
    "SCHEME_SPECS",
    "SCHEME_DRIVERS",
    "SchemeDriver",
    "CITATION_TYPE_DRIVERS",
    "CitationTypeDriver",
    "citation_type_driver",
]
