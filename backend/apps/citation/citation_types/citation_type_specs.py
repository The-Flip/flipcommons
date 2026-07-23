"""The citation-type author's declarations.

**This module is the authoring surface for a citation type** — book,
magazine, web, video — the first-party plugin unit. Unlike a scheme, a
citation type *is allowed real programming*: its module owns code (video's
timestamp grammar, its ``VideoSchemeSpec`` scheme contract), declared to the
framework as fields on these contracts. The rule here is narrower than the
scheme-side pure-configuration rule: the :class:`CitationTypeSpec` *record*
itself stays fields-only (behavior belongs in the :class:`LocatorContract`
callables and the type's own module), so everything the registry and codegen
read off a type spec is uniform field data.

Scheme authoring is deliberately not visible from here or from type modules'
customers — it lives in ``citation_scheme_specs``; the one cross-axis
reference is ``CitationTypeSpec.scheme_spec_type``, the static face of the
composition contract (a type names the spec class its schemes construct).

A model-free leaf: imports the shared ``vocabulary`` and, for that one
cross-reference, ``citation_scheme_specs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from apps.citation.citation_types.citation_scheme_specs import SchemeSpec
from apps.citation.citation_types.vocabulary import SourceType, StartSeconds

# ---------------------------------------------------------------------------
# Locator callback contracts. Named Protocols (not bare ``Callable[...]``) so
# a type author sees what each argument means in the signature itself. Params
# are positional-only, so implementations may use their own semantic names.
# These are the type author's *programming* surface: the functions a type
# module writes and declares as ``LocatorContract`` fields.
# ---------------------------------------------------------------------------


class LocatorNormalizer(Protocol):
    """Validates + canonicalizes a non-empty locator; ``None`` means invalid."""

    def __call__(self, locator: str, /) -> str | None: ...


class LocatorValueParser(Protocol):
    """Parses locator-value text to the type's structured value."""

    def __call__(self, locator: str, /) -> StartSeconds | None: ...


class LocatorValueFormatter(Protocol):
    """Formats the type's structured value as canonical locator text."""

    def __call__(self, value: StartSeconds, /) -> str: ...


# The frontend input behavior key for a locator, exported via codegen:
# ``freeform`` renders a plain text input with no validation; ``timestamp``
# adds the type's inline validation. It does NOT gate whether a locator may be
# *stored* — that is the contract's ``normalize``. (``skip_locator`` — whether
# the cite picker prompts for a locator at all — is the separate
# ``child_skips_locator`` trait; a web child's stored locator is legal either
# way, per the patch grammar and the edit panel's collapsed affordance.)
type LocatorKind = Literal["freeform", "timestamp"]


def _freeform_normalize(raw: str) -> str:
    return raw


@dataclass(frozen=True, slots=True)
class LocatorContract:
    """How one citation type's locators behave.

    - ``label`` is the contributor-facing field label in the cite picker
      (video: "Start time"; freeform: "Location in source"). A visible label,
      not a placeholder — the guidance must survive the user typing.
    - ``help`` is persistent format guidance shown under the label. Distinct
      from ``placeholder`` (a ghost example that disappears on input) and from
      ``invalid_message`` (shown only after a failed ``normalize``).
    - ``display_prefix`` prefixes the locator when a *reader* sees it (the
      citation tooltip, references list). A video's bare ``1:02:03`` reads as
      the runtime; ``"starting at"`` makes it "starting at 1:02:03" — a start
      point. Empty for freeform types, whose user-typed locators ("p. 42")
      self-describe.
    - ``normalize`` validates and canonicalizes a non-empty locator string,
      returning ``None`` for an invalid one. Empty locators never reach it —
      a locator is optional on every type.
    - ``parse_value`` / ``format_value`` bridge value text and the type's
      structured value, present only when the type has one (video: start
      seconds). ``parse_value`` is the type's whole value grammar: it parses
      stored locator text for the deep-link weave *and* the raw param values
      a scheme's ``start_seconds_source`` yields (``95``, ``1h2m3s``) — both
      woven framework-side in the registry. ``format_value`` renders a URL
      hint as locator text.
    - ``invalid_message`` is the contributor-facing error for a failed
      ``normalize``.
    """

    kind: LocatorKind
    placeholder: str
    label: str
    normalize: LocatorNormalizer = _freeform_normalize
    parse_value: LocatorValueParser | None = None
    format_value: LocatorValueFormatter | None = None
    invalid_message: str = ""
    help: str = ""
    display_prefix: str = ""


FREEFORM_LOCATOR = LocatorContract(
    kind="freeform",
    placeholder="p. 42, Chapter 3, timestamp...",
    label="Location in source",
    help="e.g. p. 42, Chapter 3, a timestamp",
)


@dataclass(frozen=True, slots=True)
class CitationTypeSpec:
    """One citation type's behavior facts, read by shared code via the registry.

    A plain record — the type's *code* lives in its module's functions and
    the ``LocatorContract`` callables, never as methods here. The human label
    is the ``SourceType`` choice label (``spec.source_type.label``).

    - ``flat_hierarchy``: the type nests exactly one level (root → child). A
      grandchild is rejected (see ``CitationSource.clean``) so recognition can
      always resolve a host to the root and mint a child directly under it.
    - ``schemeless_parentless_abstract``: whether a *schemeless* parentless
      source of this type is a container (a website, a publication), not
      directly-citable evidence — the UI steers away from citing it directly.
      Read only for the no-scheme case: a parentless source *with* an
      ``identifier_key`` is a platform/site root, always abstract (recognition
      resolves to its children), handled universally in
      ``CitationSource.is_abstract`` rather than per type. So this governs only
      the schemeless form: a parentless *book* is the work itself (citable), a
      schemeless parentless *video* is a **movie** (citable), while a magazine
      or a site is a container (abstract).
    - ``child_skips_locator``: a child of this type carries its own locator
      (its URL), so the cite picker skips the locator prompt and cites it
      one-click. Unprompted, not unavailable: the edit-evidence panel keeps a
      collapsed affordance and patches may store one.
    - ``slug_addressed``: sources of this type are addressed by an authored
      kebab slug — root-unique, sibling-unique — making
      ``<root-slug>:<child-slug>`` a legal patch cite ref (a magazine issue:
      ``billboard:1945-09-29``). For every other type the identifier already
      exists (a book's ISBN, a site's recognition domain, a scheme's key), so
      only a type with no natural identifier turns this on. Slugs are authored,
      never minted: a cite of an undeclared slug fails, exactly like ``isbn:``.
    - ``locator``: the type's locator contract (grammar, prompt, structured
      value bridge).
    - ``scheme_spec_type``: the spec class this type's schemes implement — the
      per-type contract (a video scheme must be a ``VideoSchemeSpec``).
      Enforced at import by the registry's ``isinstance`` check and by the
      conformance harness, **not** statically: ``VideoSchemeSpec`` adds no
      fields over ``SchemeSpec`` today, so a plain ``SchemeSpec`` built under a
      video ``source_type`` still type-checks. Static enforcement arrives for
      free once the subclass carries a required field a plain ``SchemeSpec``
      would be missing.
    """

    source_type: SourceType
    flat_hierarchy: bool
    schemeless_parentless_abstract: bool
    child_skips_locator: bool
    slug_addressed: bool
    locator: LocatorContract = FREEFORM_LOCATOR
    scheme_spec_type: type[SchemeSpec] = SchemeSpec
