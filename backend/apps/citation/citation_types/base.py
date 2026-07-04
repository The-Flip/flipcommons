"""Core contracts for citation-type and scheme plugins.

A dependency-free leaf (like ``hosts.py``): it owns ``SourceType`` and the
spec dataclasses but imports no app models, so ``models`` can import it
one-way without a cycle. ``CitationSource`` re-exports ``SourceType`` as
``CitationSource.SourceType`` so that stays the canonical, Django-idiomatic
handle.

Two plugin units live behind these contracts (see
``docs/plans/citations/VideoCitations.md``):

- A **citation type** (:class:`CitationTypeSpec`) — book, magazine, web,
  video — owns the per-type behavior shared code would otherwise branch on:
  hierarchy shape, abstractness, and the locator contract (grammar, prompt,
  structured value).
- A **scheme** (:class:`SchemeSpec`) — ipdb, opdb, youtube — owns one
  platform's URL recognition: how to pull an identifier out of any of the
  platform's URL shapes, validate a bare identifier, and build the canonical
  URL every shape collapses to. A scheme belongs to exactly one citation type
  (``source_type``), which is what its children mint as, and implements that
  type's ``scheme_spec_type`` contract.

The layering rule that keeps schemes small — the **composition contract**
binding the two axes: **the type owns locator semantics; a scheme speaks only
structured values.** A video scheme is handed an identifier and start seconds
— never locator text. Its reference implementation is
``registry.scheme_deep_link``: the owning type's ``parse_value`` turns locator
text into the structured value, the scheme's ``deep_link`` turns the value
into a seek URL, and neither layer sees the other's vocabulary.

Specs are **pure**: no model imports, no DB access, no I/O — all DB work
(child minting, recognition queries, instance writes) stays in core code
that consumes these specs. Scheme specs are purer still — **pure
configuration**: patterns, templates and declarative facts, no code, so a
scheme's capabilities are bounded by construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol, TypeGuard, get_args
from urllib.parse import parse_qs, urlparse

from django.db import models

# Semantic aliases (intent only, no checker safety — the ``Slug = str``
# pattern from docs/Python.md). ``SchemeKey`` is a scheme's ``identifier_key``
# value ("youtube"); ``StartSeconds`` is a video start position in whole
# seconds — the one structured locator value that currently exists, shared by
# the locator bridge (parse/format) and scheme deep links so the "type owns
# the value, scheme consumes it" symmetry is visible in the signatures.
SchemeKey = str
StartSeconds = int


class SourceType(models.TextChoices):
    BOOK = "book", "Book"
    MAGAZINE = "magazine", "Magazine"
    WEB = "web", "Web"
    VIDEO = "video", "Video"


# The Literal twin of ``SourceType``, for **internal** Python contracts
# (TypedDicts, test factories, helper signatures). Deliberately NOT used on
# Ninja ``Schema`` fields — wire scalars stay bare ``str`` per
# ``docs/Python.md`` so internal renames never surface as schema diffs. A
# Literal can't be derived from the enum, so the import-time assertion below
# keeps the hand-mirrored list honest.
CitationSourceTypeValue = Literal["book", "magazine", "web", "video"]


def _assert_citation_source_type_literal_current() -> None:
    """Raise at import if ``CitationSourceTypeValue`` drifts from ``SourceType``."""
    literal = set(get_args(CitationSourceTypeValue))
    if literal != set(SourceType.values):
        raise AssertionError(
            f"CitationSourceTypeValue {sorted(literal)} != SourceType {sorted(SourceType.values)}"
        )


_assert_citation_source_type_literal_current()

_CITATION_SOURCE_TYPE_VALUES: frozenset[str] = frozenset(
    get_args(CitationSourceTypeValue)
)


def _is_citation_source_type(raw: str) -> TypeGuard[CitationSourceTypeValue]:
    return raw in _CITATION_SOURCE_TYPE_VALUES


def citation_source_type(raw: str) -> CitationSourceTypeValue:
    """Coerce a model's raw ``source_type`` field to the typed Literal.

    The typed-contract twin of ``citation_type_spec``'s coercion: a stored
    value outside the registered types (impossible under the CHECK constraint,
    reachable only via raw SQL) raises ``ValueError`` instead of leaking an
    unvalidated string into a typed structure (e.g. ``ExtractionMatch``).
    """
    if _is_citation_source_type(raw):
        return raw
    raise ValueError(f"Unknown source_type {raw!r}")


# ---------------------------------------------------------------------------
# Locator callback contracts (type-side). Named Protocols (not bare
# ``Callable[...]``) so a type author sees what each argument means in the
# signature itself. Params are positional-only, so implementations may use
# their own semantic names. Scheme-side capabilities carry no callbacks at
# all — a scheme is pure configuration (templates + declarative sources).
# ---------------------------------------------------------------------------


class LocatorNormalizer(Protocol):
    """Validates + canonicalizes a non-empty locator; ``None`` means invalid."""

    def __call__(self, locator: str, /) -> str | None: ...


class LocatorValueParser(Protocol):
    """Parses canonical locator text to the type's structured value."""

    def __call__(self, locator: str, /) -> StartSeconds | None: ...


class LocatorValueFormatter(Protocol):
    """Formats the type's structured value as canonical locator text."""

    def __call__(self, value: StartSeconds, /) -> str: ...


@dataclass(frozen=True, slots=True)
class StartSecondsSource:
    """Where a platform's URLs carry a start-time hint — declarative, no code.

    A scheme declares only the *location*: named parameters read from the URL
    query (YouTube's ``?t=``/``?start=``) or fragment (Vimeo's ``#t=``). The
    parameter *values* are parsed by the owning type's URL-value grammar (the
    ``_parse_url_seconds`` hook on its scheme-spec subclass) — the scheme says
    where, the type says what it means.
    """

    location: Literal["query", "fragment"]
    params: tuple[str, ...]

    def raw_values(self, url: str) -> list[str]:
        """The declared parameters' raw string values in *url*, params-major.

        A URL too malformed for ``urlparse`` yields ``[]`` rather than raising.
        """
        try:
            parsed = urlparse(url)
        except ValueError:
            return []
        text = parsed.query if self.location == "query" else parsed.fragment
        found = parse_qs(text)
        return [value for name in self.params for value in found.get(name, [])]


@dataclass(frozen=True, slots=True)
class SchemeMatch:
    """A URL recognized by a scheme: the identifier, plus structured hints.

    ``start_seconds`` is the start-time hint a video-platform URL may carry
    (``?t=95``); schemes without time semantics always leave it ``None``. It is
    a structured value — the owning *type* formats it to a locator string; a
    scheme never produces locator text.
    """

    identifier: str
    start_seconds: StartSeconds | None = None


@dataclass(frozen=True, slots=True)
class SchemeRootCitationSourceInfo:
    """Declarative facts about a scheme's platform root ``CitationSource``.

    The root row is still created by a data patch — a scheme is live only once
    its root is seeded — but the patch is authored from these facts, and the
    ingest validation (``_validate_scheme_root_citation_source_info`` in
    ``source_upsert``) rejects a ``sources:`` declaration that disagrees with
    them, so the registry stays operationally authoritative.
    ``recognition_hosts`` are the ``CitationSourceRootDomain`` hosts the root
    should own (normalized: lowercase, no ``www.``).
    """

    name: str
    homepage_url: str
    recognition_hosts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemeSpec:
    """One platform's identifier scheme: URL recognition + canonical URL.

    The third-party plugin unit, and **pure configuration**: every field is
    data (patterns, templates, declarative facts) — a scheme carries no code,
    which is what makes its capabilities bounded and (eventually) plausible
    as UI-built, DB-stored rows. The shared ``extract``/``validate_identifier``
    /``normalize`` methods drive the fields, so every scheme resolves input
    the same way. Conventions the conformance harness enforces:

    - ``url_pattern`` captures the identifier in **exactly one participating
      group** (alternation branches may each carry their own capture, so each
      URL shape can enforce its own boundary) and is anchored on
      ``https?://<host>`` so a look-alike host (``notyoutube.com``) can't match.
    - ``id_pattern`` fullmatches a bare identifier.
    - ``canonical_url_template`` is a ``str.format`` template with exactly one
      placeholder, ``{identifier}``, building the one URL every shape
      collapses to — ``extract(canonical_url(id))`` must round-trip. Template
      substitution suffices by construction: the recognition contract already
      requires the identifier to be one contiguous substring of the URL
      (TikTok's composite ``user/video/id`` identity is designed around it).

    The two optional capabilities speak the owning type's structured locator
    value (see ``LocatorContract``), never locator text:

    - ``deep_link_template`` adds ``{start_seconds}`` to the placeholders and
      builds the URL that jumps to a structured position (video: the watch
      URL with ``t=``). Optional even on value-carrying types — some
      platforms' URLs simply cannot seek (TikTok); their citations render the
      locator text beside the plain canonical link.
    - ``start_seconds_source`` declares where a recognized URL carries the
      structured position hint (``?t=95``), surfaced by ``extract`` as
      ``SchemeMatch.start_seconds``; the owning type's spec subclass parses
      the values (``_parse_url_seconds``). A scheme declaring this must also
      provide ``deep_link_template`` (conformance-enforced): URLs that carry
      seek positions prove the platform can jump.
    """

    key: SchemeKey
    label: str
    source_type: SourceType
    url_pattern: re.Pattern[str]
    id_pattern: re.Pattern[str]
    canonical_url_template: str
    root_citation_source_info: SchemeRootCitationSourceInfo
    deep_link_template: str | None = None
    start_seconds_source: StartSecondsSource | None = None

    # -- Framework surface. The methods below are defined once, here, and
    # invoked by the citation framework ON the fields above — a scheme author
    # fills in the fields and never writes or overrides these (the one
    # exception is ``_parse_url_seconds``, overridden per owning *type*, not
    # per scheme). The single shared implementation is what guarantees every
    # scheme resolves input identically; the conformance harness exercises
    # them against every registered scheme. --

    def canonical_url(self, identifier: str) -> str:
        """The one URL every recognized shape of *identifier* collapses to."""
        return self.canonical_url_template.format(identifier=identifier)

    def deep_link(self, identifier: str, start_seconds: StartSeconds) -> str | None:
        """The URL that jumps to *start_seconds* within *identifier*.

        ``None`` when the scheme declares no ``deep_link_template`` — the
        platform's URLs cannot seek.
        """
        if self.deep_link_template is None:
            return None
        return self.deep_link_template.format(
            identifier=identifier, start_seconds=start_seconds
        )

    def _parse_url_seconds(self, value: str) -> StartSeconds | None:
        """Parse one raw ``start_seconds_source`` param value into seconds.

        The composition contract's hook: the scheme declares *where* the hint
        lives, the owning type's scheme-spec subclass declares *what the
        values mean* by overriding this with its grammar (video accepts
        ``95``, ``95s``, ``1h2m3s``). The base scheme has no value grammar,
        so a ``start_seconds_source`` on a plain ``SchemeSpec`` is inert.
        """
        return None

    def _start_seconds_hint(self, url: str) -> StartSeconds | None:
        """Evaluate ``start_seconds_source`` against *url*.

        First parseable, nonzero value wins (``t=0`` means "from the start" —
        no hint); ``None`` when the scheme declares no source.
        """
        if self.start_seconds_source is None:
            return None
        for raw in self.start_seconds_source.raw_values(url):
            seconds = self._parse_url_seconds(raw)
            if seconds:
                return seconds
        return None

    def extract(self, url: str) -> SchemeMatch | None:
        """Recognize *url* as one of this scheme's shapes, or ``None``."""
        m = self.url_pattern.search(url)
        if m is None:
            return None
        # Exactly one alternation branch participates, so its capture is the
        # highest-numbered matched group — per-branch captures let each URL
        # shape carry its own boundary (a query id may be followed by ``&``,
        # a path id may not grow extra path segments).
        assert m.lastindex is not None, "url_pattern must capture the identifier"
        return SchemeMatch(
            identifier=m.group(m.lastindex),
            start_seconds=self._start_seconds_hint(url),
        )

    def validate_identifier(self, raw: str) -> str | None:
        """Return *raw* when it is a well-formed bare identifier, else ``None``."""
        return raw if self.id_pattern.fullmatch(raw) else None

    def normalize(self, raw: str) -> str | None:
        """Extract a valid identifier from a URL or bare value, or ``None``.

        Tries the URL shapes first, then validates as a bare identifier.
        """
        match = self.extract(raw)
        if match is not None:
            return match.identifier
        return self.validate_identifier(raw)


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

    - ``normalize`` validates and canonicalizes a non-empty locator string,
      returning ``None`` for an invalid one. Empty locators never reach it —
      a locator is optional on every type.
    - ``parse_value`` / ``format_value`` bridge locator text and the type's
      structured value, present only when the type has one (video: start
      seconds): ``parse_value`` feeds scheme ``deep_link`` builders,
      ``format_value`` renders a scheme's ``SchemeMatch`` hint as locator text.
    - ``invalid_message`` is the contributor-facing error for a failed
      ``normalize``.
    """

    kind: LocatorKind
    placeholder: str
    normalize: LocatorNormalizer = _freeform_normalize
    parse_value: LocatorValueParser | None = None
    format_value: LocatorValueFormatter | None = None
    invalid_message: str = ""


FREEFORM_LOCATOR = LocatorContract(
    kind="freeform",
    placeholder="p. 42, Chapter 3, timestamp...",
)


@dataclass(frozen=True, slots=True)
class CitationTypeSpec:
    """One citation type's behavior facts, read by shared code via the registry.

    - ``flat_hierarchy``: the type nests exactly one level (root → child). A
      grandchild is rejected (see ``CitationSource.clean``) so recognition can
      always resolve a host to the root and mint a child directly under it.
    - ``parentless_abstract``: a parentless source of this type is a container
      (a website, a publication), not directly-citable evidence — the UI steers
      away from citing it directly. A parentless *book* is the work itself, so
      it is citable.
    - ``child_skips_locator``: a child of this type carries its own locator
      (its URL), so the cite picker skips the locator prompt and cites it
      one-click. Unprompted, not unavailable: the edit-evidence panel keeps a
      collapsed affordance and patches may store one.
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
    parentless_abstract: bool
    child_skips_locator: bool
    locator: LocatorContract = FREEFORM_LOCATOR
    scheme_spec_type: type[SchemeSpec] = SchemeSpec

    @property
    def label(self) -> str:
        """The human-facing type label (the ``SourceType`` choice label)."""
        return self.source_type.label
