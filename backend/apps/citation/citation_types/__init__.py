"""Citation-type and scheme plugins, behind one registry.

The package root is the plugin system's public surface, and it serves two
audiences with two distinct import surfaces (the sections in ``__all__``
below; see ``docs/plans/citations/CitationPluginSystem.md``):

- **Plugin authors** — writing one scheme or type — import the contract
  types, callback Protocols and authoring helpers, and see only what they
  must fill in.
- **External customers** — code that uses the citation system without
  knowing a plugin exists — import the named registry accessors
  (``citation_type_spec``, ``recognize_scheme``, …) and never read a spec's
  fields.

The third surface, the **citation framework** itself (the shared
``SchemeSpec`` driver methods, the registry coherence checks, the
conformance harness), is not an import surface: it is documented where it
lives, in ``base.py`` and ``registry.py``. The raw spec mappings exported
last are its channel — consumed only by the framework's own DB operations
(``extractors``/``deep_links``), the codegen commands and tests.
"""

from apps.citation.citation_types.base import (
    CanonicalUrlBuilder,
    CitationSourceTypeValue,
    CitationTypeSpec,
    DeepLinkBuilder,
    LocatorContract,
    SchemeKey,
    SchemeMatch,
    SchemeRootCitationSourceInfo,
    SchemeSpec,
    SourceType,
    StartSeconds,
    StartSecondsExtractor,
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
    scheme_canonical_url,
    scheme_deep_link,
    scheme_root_citation_source_info,
    scheme_source_type,
)
from apps.citation.citation_types.url_patterns import ID_BOUNDARY, host_prefix

__all__ = [
    # ----- Plugin-author surface: what a scheme or type author fills in -----
    "SchemeSpec",
    "SchemeRootCitationSourceInfo",
    "SchemeMatch",
    "CanonicalUrlBuilder",
    "DeepLinkBuilder",
    "StartSecondsExtractor",
    "host_prefix",
    "ID_BOUNDARY",
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
    "scheme_root_citation_source_info",
    "is_known_scheme",
    "known_scheme_keys",
    "citation_source_type",
    # ----- Shared vocabulary: semantic aliases and the type enum -----
    "SourceType",
    "CitationSourceTypeValue",
    "SchemeKey",
    "StartSeconds",
    # ----- Framework channel: constraint derivation (models) and the raw
    # spec mappings (extractors/deep_links, codegen, tests only) -----
    "identifier_key_values",
    "identifier_key_choices",
    "SchemeChoice",
    "scheme_bindings",
    "SchemeBinding",
    "CITATION_TYPE_SPECS",
    "SCHEME_SPECS",
]
