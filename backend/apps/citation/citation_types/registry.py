"""The aggregating registry for citation types and schemes.

The single place that names the registered plugins. Core code (models,
recognition, ingest, API) reads types and schemes from here — never from a
plugin module directly and never via a hand-listed enum — so adding a scheme
is one module under ``schemes/`` plus one line in ``_SCHEMES`` below, and
adding a type is one module plus one line in ``_CITATION_TYPES``. The model's
CHECK-constraint value lists derive from these registrations, so a new entry
flows into ``makemigrations`` instead of a hand-edit.

Registration is deliberately an explicit list, not directory auto-discovery:
greppable beats magic, and the import-time assertions below catch a module
that was written but never registered as soon as its key is used anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from apps.citation.citation_types import book, magazine, video, web
from apps.citation.citation_types.base import CitationTypeSpec, SchemeSpec, SourceType
from apps.citation.citation_types.schemes import ipdb, opdb, youtube

_CITATION_TYPES: Final[tuple[CitationTypeSpec, ...]] = (
    book.BOOK,
    magazine.MAGAZINE,
    web.WEB,
    video.VIDEO,
)

# Ordering is load-bearing twice over: recognition tries schemes in this order,
# and the derived CHECK value list serializes in this order (reordering would
# churn a migration).
_SCHEMES: Final[tuple[SchemeSpec, ...]] = (
    ipdb.IPDB,
    opdb.OPDB,
    youtube.YOUTUBE,
)

CITATION_TYPE_SPECS: Final[Mapping[SourceType, CitationTypeSpec]] = {
    spec.source_type: spec for spec in _CITATION_TYPES
}

SCHEME_SPECS: Final[Mapping[str, SchemeSpec]] = {spec.key: spec for spec in _SCHEMES}


def _assert_registry_coherent(
    types: Mapping[SourceType, CitationTypeSpec],
    schemes: Mapping[str, SchemeSpec],
) -> None:
    """Raise if the registry is incomplete or inconsistent.

    Helpers (not bare module-level ``assert``s) so a test can call them
    directly against a deliberately-broken registry — no ``importlib.reload``.
    Called once at import below, so a bad registration fails at load, not at
    the first runtime lookup:

    - every ``SourceType`` member has a type spec;
    - no two type specs or scheme specs claimed one key (a dict-comprehension
      collision drops a row silently — compare against the source tuples);
    - every scheme's ``source_type`` is a registered type.
    """
    missing = set(SourceType) - types.keys()
    if missing:
        raise AssertionError(f"SourceType(s) missing a type spec: {sorted(missing)}")
    if len(types) != len(_CITATION_TYPES):
        raise AssertionError("Two citation type specs registered one source_type.")
    if len(schemes) != len(_SCHEMES):
        raise AssertionError("Two scheme specs registered one key.")
    orphaned = [spec.key for spec in schemes.values() if spec.source_type not in types]
    if orphaned:
        raise AssertionError(f"Scheme(s) with an unregistered source_type: {orphaned}")
    # Each scheme implements its owning type's contract — the per-type Protocol
    # (a video scheme must be a VideoSchemeSpec, which requires deep_link).
    # mypy enforces this statically inside each scheme module; this is the
    # runtime backstop for a spec registered under the wrong type.
    nonconforming = [
        spec.key
        for spec in schemes.values()
        if spec.source_type in types
        and not isinstance(spec, types[spec.source_type].scheme_spec_type)
    ]
    if nonconforming:
        raise AssertionError(
            f"Scheme(s) not implementing their type's scheme_spec_type: {nonconforming}"
        )


_assert_registry_coherent(CITATION_TYPE_SPECS, SCHEME_SPECS)


def citation_type_spec(source_type: str | SourceType) -> CitationTypeSpec:
    """The type spec for *source_type*, coercing a raw field value.

    The single typed chokepoint: callers pass a model's ``source_type``
    ``CharField`` (typed ``str``) and get the spec back, with the coercion
    validating the value — an unknown string raises ``ValueError`` rather than
    a ``KeyError`` or a silent miss. Never index ``CITATION_TYPE_SPECS`` with a
    bare field value.
    """
    return CITATION_TYPE_SPECS[SourceType(source_type)]


def identifier_key_values() -> list[str]:
    """The registered scheme keys, in registration order.

    The value list behind the ``identifier_key`` CHECK constraint (with ``""``
    prepended by the model — blank means a root without a scheme).
    """
    return list(SCHEME_SPECS)


def identifier_key_choices() -> list[tuple[str, str]]:
    """``(value, label)`` choices for the ``identifier_key`` field."""
    return [(spec.key, spec.label) for spec in SCHEME_SPECS.values()]


def scheme_bearing_source_types() -> list[str]:
    """The source types that own at least one registered scheme.

    In ``SourceType`` definition order (stable, so the derived CHECK
    constraint doesn't churn a migration when a scheme is added to an
    already-bearing type). The value list behind the model's
    "``identifier_key`` only on scheme-bearing types" CHECK.
    """
    bearing = {spec.source_type for spec in SCHEME_SPECS.values()}
    return [st.value for st in SourceType if st in bearing]
