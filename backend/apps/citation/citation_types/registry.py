"""The aggregating registry for citation types and schemes.

The single place core code (models, recognition, ingest, API) reads types and
schemes from. Citation types remain explicitly registered first-party product
concepts. Schemes are auto-discovered plugin declarations: a module under
``schemes/`` exports one conventional ``SCHEME`` value, and the registry imports
those modules in deterministic key order. The model's CHECK-constraint value
lists derive from these registrations, so a new scheme flows into
``makemigrations`` instead of a hand-edit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, NamedTuple

from apps.citation.citation_types import book, document, periodical, video, web
from apps.citation.citation_types import schemes as scheme_package
from apps.citation.citation_types.citation_scheme_driver import (
    SchemeDriver,
    start_seconds_hint_values,
)
from apps.citation.citation_types.citation_scheme_specs import (
    SchemeKey,
    SchemeRootCitationSourceInfo,
    SchemeSpec,
)
from apps.citation.citation_types.citation_type_driver import CitationTypeDriver
from apps.citation.citation_types.citation_type_specs import CitationTypeSpec
from apps.citation.citation_types.plugin_discovery import discover_package_exports
from apps.citation.citation_types.vocabulary import SourceType, StartSeconds

_CITATION_TYPES: Final[tuple[CitationTypeSpec, ...]] = (
    book.BOOK,
    periodical.PERIODICAL,
    web.WEB,
    video.VIDEO,
    document.DOCUMENT,
)

_SCHEME_EXPORT: Final = "SCHEME"


def _discover_scheme_specs() -> tuple[SchemeSpec, ...]:
    """Import every scheme module and return its conventional ``SCHEME`` value.

    Discovery is deliberately narrow: only immediate, non-private modules in
    ``citation_types/schemes`` participate; each must export exactly one
    ``SchemeSpec`` under ``SCHEME``. Sorting by scheme key gives stable
    recognition and migration ordering independent of filesystem order — safe
    because ``_assert_registry_coherent`` requires the schemes' URL-shape hosts
    to be disjoint, so first-match recognition can't depend on which scheme
    happens to sort first.
    """
    discovered = discover_package_exports(
        scheme_package,
        _SCHEME_EXPORT,
        SchemeSpec,
        include_module=lambda name: not name.startswith("_"),
    )
    return tuple(sorted((d.value for d in discovered), key=lambda spec: spec.key))


_SCHEMES: Final[tuple[SchemeSpec, ...]] = _discover_scheme_specs()

CITATION_TYPE_SPECS: Final[Mapping[SourceType, CitationTypeSpec]] = {
    spec.source_type: spec for spec in _CITATION_TYPES
}

SCHEME_SPECS: Final[Mapping[SchemeKey, SchemeSpec]] = {
    spec.key: spec for spec in _SCHEMES
}


def _assert_registry_coherent(
    types: Mapping[SourceType, CitationTypeSpec],
    schemes: tuple[SchemeSpec, ...],
) -> None:
    """Raise if the registry is incomplete or inconsistent.

    Helpers (not bare module-level ``assert``s) so a test can call them
    directly against a deliberately-broken registry — no ``importlib.reload``.
    Called once at import below, so a bad registration fails at load, not at
    the first runtime lookup:

    - every ``SourceType`` member has a type spec;
    - no two type specs or scheme specs claimed one key (a dict-comprehension
      collision drops a row silently — compare against the source tuples);
    - every scheme's ``source_type`` is a registered type;
    - no two schemes share a URL-shape host, so ``recognize_scheme``'s
      first-match-wins order is irrelevant to the result.
    """
    missing = set(SourceType) - types.keys()
    if missing:
        raise AssertionError(f"SourceType(s) missing a type spec: {sorted(missing)}")
    if len(types) != len(_CITATION_TYPES):
        raise AssertionError("Two citation type specs registered one source_type.")
    scheme_map = {spec.key: spec for spec in schemes}
    if len(scheme_map) != len(schemes):
        raise AssertionError("Two scheme specs registered one key.")
    orphaned = [spec.key for spec in schemes if spec.source_type not in types]
    if orphaned:
        raise AssertionError(f"Scheme(s) with an unregistered source_type: {orphaned}")
    # Each scheme implements its owning type's contract — the per-type spec
    # class (a video scheme must be a VideoSchemeSpec). This isinstance check
    # and the conformance harness are what enforce it: VideoSchemeSpec adds no
    # fields today, so a plain SchemeSpec under a video source_type type-checks,
    # making this import-time check the earliest catch. It becomes statically
    # enforced for free once the subclass gains a required field.
    nonconforming = [
        spec.key
        for spec in schemes
        if spec.source_type in types
        and not isinstance(spec, types[spec.source_type].scheme_spec_type)
    ]
    if nonconforming:
        raise AssertionError(
            f"Scheme(s) not implementing their type's scheme_spec_type: {nonconforming}"
        )
    # Recognition is first-match-wins over schemes in key order (see
    # ``recognize_scheme``), which is only order-independent if no URL can match
    # two schemes. Every shape is host-anchored, so disjoint URL-shape hosts
    # across schemes are sufficient — and enforced here at import, so a host
    # collision fails the build rather than resolving to whichever scheme sorts
    # first.
    host_owners: dict[str, list[SchemeKey]] = {}
    for spec in schemes:
        for host in {host for shape in spec.url_shapes for host in shape.hosts}:
            host_owners.setdefault(host, []).append(spec.key)
    collisions = {
        host: sorted(keys) for host, keys in host_owners.items() if len(keys) > 1
    }
    if collisions:
        raise AssertionError(f"Schemes share URL-shape hosts: {collisions}")


_assert_registry_coherent(CITATION_TYPE_SPECS, _SCHEMES)

# One framework driver per registered plugin, in registration order.
# Building the scheme drivers here compiles every scheme's declarations at
# import, so a malformed spec fails the build, not the first recognition.
# The specs stay pure data on both axes; all behavior runs through these.
SCHEME_DRIVERS: Final[Mapping[SchemeKey, SchemeDriver]] = {
    key: SchemeDriver(spec) for key, spec in SCHEME_SPECS.items()
}

CITATION_TYPE_DRIVERS: Final[Mapping[SourceType, CitationTypeDriver]] = {
    source_type: CitationTypeDriver(spec)
    for source_type, spec in CITATION_TYPE_SPECS.items()
}


def citation_type_spec(source_type: str | SourceType) -> CitationTypeSpec:
    """The type spec for *source_type*, coercing a raw field value.

    The single typed chokepoint: callers pass a model's ``source_type``
    ``CharField`` (typed ``str``) and get the spec back, with the coercion
    validating the value — an unknown string raises ``ValueError`` rather than
    a ``KeyError`` or a silent miss. Never index ``CITATION_TYPE_SPECS`` with a
    bare field value.
    """
    return CITATION_TYPE_SPECS[SourceType(source_type)]


def citation_type_driver(source_type: str | SourceType) -> CitationTypeDriver:
    """The framework driver for *source_type*, coercing a raw field value.

    The behavioral twin of :func:`citation_type_spec`: consumers that need to
    *run* a type's locator grammar (validate, parse, format) get the driver;
    consumers that read behavior facts get the spec.
    """
    return CITATION_TYPE_DRIVERS[SourceType(source_type)]


def identifier_key_values() -> list[SchemeKey]:
    """The registered scheme keys, in registration order.

    The value list behind the ``identifier_key`` CHECK constraint (with ``""``
    prepended by the model — blank means a root without a scheme).
    """
    return list(SCHEME_SPECS)


class SchemeChoice(NamedTuple):
    """One ``choices`` entry for the ``identifier_key`` field."""

    value: SchemeKey
    label: str


def identifier_key_choices() -> list[SchemeChoice]:
    """Choices for the ``identifier_key`` field (a ``SchemeChoice`` is a
    2-tuple, so Django's ``choices=`` accepts the list as-is)."""
    return [SchemeChoice(spec.key, spec.label) for spec in SCHEME_SPECS.values()]


class SchemeBinding(NamedTuple):
    """A scheme key bound to its owning citation type."""

    identifier_key: SchemeKey
    source_type: SourceType


def scheme_bindings() -> list[SchemeBinding]:
    """Each scheme's ``(identifier_key, owning source_type)``, registration order.

    The fact list behind the model's "a scheme root's type is its scheme's
    owning type" CHECK: ``identifier_key='youtube'`` implies
    ``source_type='video'``, so a hierarchy stays uniformly typed (a video
    platform root can't be a web source minting video children). Ordering is
    stable registration order so the derived constraint doesn't churn a
    migration on unrelated edits.
    """
    return [SchemeBinding(spec.key, spec.source_type) for spec in SCHEME_SPECS.values()]


def slug_addressed_source_types() -> list[SourceType]:
    """The source types addressed by authored slugs, in registration order.

    The value list behind the model's slug CHECKs (slug only on — and required
    on — a slug-addressed type) and the ingest validators, so turning the flag
    on for another type is a spec edit plus a backfill, never a hand-edit of
    shared code. Stable registration order for the same
    migration-churn reason as :func:`scheme_bindings`.
    """
    return [
        spec.source_type for spec in CITATION_TYPE_SPECS.values() if spec.slug_addressed
    ]


# ---------------------------------------------------------------------------
# External-customer scheme queries. Pure, read-only over ``SCHEME_SPECS`` —
# what code outside this package calls instead of reaching into spec fields,
# so a customer is coupled to these six names, never to the spec's field
# vocabulary. Their DB-resolving counterparts (``recognize_url``,
# ``deep_linked_url``, child minting) live with the DB code in
# ``extractors``/``deep_links``.
# ---------------------------------------------------------------------------


def _scheme_spec(key: SchemeKey) -> SchemeSpec:
    spec = SCHEME_SPECS.get(key)
    if spec is None:
        raise ValueError(f"Unknown scheme {key!r}")
    return spec


def _scheme_driver(key: SchemeKey) -> SchemeDriver:
    driver = SCHEME_DRIVERS.get(key)
    if driver is None:
        raise ValueError(f"Unknown scheme {key!r}")
    return driver


class SchemeRecognition(NamedTuple):
    """A URL recognized by a registered scheme, by pattern match alone.

    ``label`` rides along for customer-facing messages ("This URL is a
    YouTube record…"); ``start_seconds`` is the structured start-time hint
    the URL carried, when the scheme extracts one.
    """

    scheme: SchemeKey
    label: str
    identifier: str
    start_seconds: StartSeconds | None


def _start_seconds_hint(spec: SchemeSpec, url: str) -> StartSeconds | None:
    """Evaluate a scheme's declared ``start_seconds_source`` against *url*.

    The inbound half of the composition contract, mirroring
    ``scheme_deep_link``'s outbound weave: the scheme's source says *where*
    the hint rides in the URL, the owning type's ``locator.parse_value``
    grammar says *what the values mean* — neither layer sees the other's
    vocabulary, and the spec classes carry no parsing at all. First
    parseable, nonzero value wins (``t=0`` means "from the start" — no
    hint); a source on a type with no value grammar is inert.
    """
    source = spec.start_seconds_source
    if source is None:
        return None
    type_driver = CITATION_TYPE_DRIVERS[spec.source_type]
    for raw in start_seconds_hint_values(source, url):
        seconds = type_driver.parse_locator_value(raw)
        if seconds:
            return seconds
    return None


def scheme_start_seconds_hint(key: SchemeKey, url: str) -> StartSeconds | None:
    """The structured start-time hint *url* carries for scheme *key*, if any.

    ``ValueError`` for an unregistered key.
    """
    return _start_seconds_hint(_scheme_spec(key), url)


def recognize_scheme(url: str) -> SchemeRecognition | None:
    """Which scheme + identifier *url* yields, by pattern match alone.

    Registration order, first match wins — the same order the DB-resolving
    ``recognize_url`` tries. Pure: no seeded-root lookup, no minting. For
    callers that reject a scheme URL cited the wrong way (as a plain web
    page) regardless of whether the scheme's root is seeded yet.
    """
    for key, driver in SCHEME_DRIVERS.items():
        identifier = driver.extract(url)
        if identifier is not None:
            return SchemeRecognition(
                scheme=key,
                label=driver.spec.label,
                identifier=identifier,
                start_seconds=_start_seconds_hint(driver.spec, url),
            )
    return None


def is_known_scheme(key: str) -> bool:
    """Whether *key* is a registered scheme key."""
    return key in SCHEME_SPECS


def known_scheme_keys() -> list[SchemeKey]:
    """The registered scheme keys, in registration order."""
    return list(SCHEME_SPECS)


def scheme_source_type(key: SchemeKey) -> SourceType:
    """The citation type owning the scheme *key* — what its children mint as.

    ``ValueError`` for an unregistered key: callers holding untrusted input
    gate on ``is_known_scheme`` first.
    """
    return _scheme_spec(key).source_type


def normalize_scheme_identifier(key: SchemeKey, raw: str) -> str | None:
    """Extract a valid *key* identifier from a URL or bare value, or ``None``.

    ``None`` means *raw* is neither a recognized URL shape nor a well-formed
    bare identifier; ``ValueError`` for an unregistered key.
    """
    return _scheme_driver(key).normalize(raw)


def scheme_root_citation_source_info(key: str) -> SchemeRootCitationSourceInfo | None:
    """The declared platform-root facts for *key*, or ``None`` if unregistered.

    ``None`` (not ``ValueError``) because the caller is ingest validation
    holding a patch-declared key: an unknown key is the field validator's
    error to report, and this query must stay usable on the way there.
    """
    spec = SCHEME_SPECS.get(key)
    return spec.root_citation_source_info if spec is not None else None


def scheme_canonical_url(key: SchemeKey, identifier: str) -> str:
    """The one URL every recognized shape of *identifier* collapses to.

    ``ValueError`` for an unregistered key: callers holding untrusted input
    gate on ``is_known_scheme`` first.
    """
    return _scheme_driver(key).canonical_url(identifier)


def scheme_deep_link(key: SchemeKey, identifier: str, locator: str) -> str | None:
    """The URL that jumps to *locator* within scheme *key*'s *identifier*.

    The reference implementation of the composition contract (the type owns
    the locator value; a scheme speaks only the structured value): the
    scheme's owning *type* parses the locator text into its structured value,
    then the *scheme* builds the seek URL from that value — neither layer
    sees the other's vocabulary. ``None`` when either layer declines: the
    scheme has no ``deep_link_template`` (TikTok URLs can't seek), the type
    has no structured locator value (web's freeform locators), or the locator
    doesn't parse. ``ValueError`` for an unregistered key.
    """
    driver = _scheme_driver(key)
    if driver.spec.deep_link_template is None:
        return None
    value = CITATION_TYPE_DRIVERS[driver.spec.source_type].parse_locator_value(locator)
    if value is None:
        return None
    return driver.deep_link(identifier, value)
