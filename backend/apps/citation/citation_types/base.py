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

The layering rule that keeps schemes small: **the type owns locator
semantics; a scheme speaks only structured values.** A video scheme is handed
an identifier and start seconds — never locator text.

Specs are **pure**: declarative facts plus stateless functions. No model
imports, no DB access, no I/O — all DB work (child minting, recognition
queries, instance writes) stays in core code that consumes these specs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeGuard, get_args

from django.db import models


class SourceType(models.TextChoices):
    BOOK = "book", "Book"
    MAGAZINE = "magazine", "Magazine"
    WEB = "web", "Web"
    VIDEO = "video", "Video"


# The wire-type twin of ``SourceType``: a Literal for API schema fields so the
# OpenAPI document (and the generated frontend types) carry the value union
# instead of a bare string. A Literal can't be derived from the enum, so the
# import-time assertion below keeps the hand-mirrored list honest.
SourceTypeValue = Literal["book", "magazine", "web", "video"]


def _assert_source_type_literal_current() -> None:
    """Raise at import if ``SourceTypeValue`` drifts from ``SourceType``."""
    literal = set(get_args(SourceTypeValue))
    if literal != set(SourceType.values):
        raise AssertionError(
            f"SourceTypeValue {sorted(literal)} != SourceType {sorted(SourceType.values)}"
        )


_assert_source_type_literal_current()

_SOURCE_TYPE_VALUES: frozenset[str] = frozenset(get_args(SourceTypeValue))


def _is_source_type_value(raw: str) -> TypeGuard[SourceTypeValue]:
    return raw in _SOURCE_TYPE_VALUES


def source_type_value(raw: str) -> SourceTypeValue:
    """Coerce a model's raw ``source_type`` field to the wire Literal.

    The serializer-side twin of ``citation_type_spec``'s coercion: a stored
    value outside the registered types (impossible under the CHECK constraint,
    reachable only via raw SQL) raises ``ValueError`` instead of leaking an
    unvalidated string onto the wire.
    """
    if _is_source_type_value(raw):
        return raw
    raise ValueError(f"Unknown source_type {raw!r}")


@dataclass(frozen=True, slots=True)
class SchemeMatch:
    """A URL recognized by a scheme: the identifier, plus structured hints.

    ``start_seconds`` is the start-time hint a video-platform URL may carry
    (``?t=95``); schemes without time semantics always leave it ``None``. It is
    a structured value — the owning *type* formats it to a locator string; a
    scheme never produces locator text.
    """

    identifier: str
    start_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class RootSeed:
    """Declarative facts about a scheme's platform root ``CitationSource``.

    The root row is still created by a data patch — a scheme is live only once
    its root is seeded — but the patch is authored from these facts, and the
    ingest validation (``source_upsert._validate_scheme_root_seed``) rejects a
    ``sources:`` declaration that disagrees with them, so the registry stays
    operationally authoritative.
    ``recognition_hosts`` are the ``CitationSourceRootDomain`` hosts the root
    should own (normalized: lowercase, no ``www.``).
    """

    name: str
    homepage_url: str
    recognition_hosts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemeSpec:
    """One platform's identifier scheme: URL recognition + canonical URL.

    The third-party plugin unit. An author supplies host-anchored patterns and
    a canonical-URL builder; the shared ``extract``/``validate_identifier``/
    ``normalize`` methods drive them, so every scheme resolves input the same
    way. Conventions the conformance harness enforces:

    - ``url_pattern`` captures the identifier in **exactly one participating
      group** (alternation branches may each carry their own capture, so each
      URL shape can enforce its own boundary) and is anchored on
      ``https?://<host>`` so a look-alike host (``notyoutube.com``) can't match.
    - ``id_pattern`` fullmatches a bare identifier.
    - ``canonical_url`` builds the one URL every shape collapses to —
      ``extract(canonical_url(id))`` must round-trip.
    - ``example_identifier`` is a real, well-formed identifier; it seeds the
      harness's round-trip checks and doubles as documentation.

    The two optional capabilities speak the owning type's structured locator
    value (see ``LocatorContract``), never locator text:

    - ``deep_link`` builds the URL that jumps to a structured position
      (video: ``(identifier, start_seconds) -> watch URL with t=``). Types
      whose locator carries a value require it via their ``scheme_spec_type``.
    - ``start_seconds_from_url`` pulls the structured position hint out of a
      recognized URL (``?t=95``), surfaced by ``extract`` as
      ``SchemeMatch.start_seconds``.
    """

    key: str
    label: str
    source_type: SourceType
    url_pattern: re.Pattern[str]
    id_pattern: re.Pattern[str]
    canonical_url: Callable[[str], str]
    example_identifier: str
    root_seed: RootSeed
    deep_link: Callable[[str, int], str] | None = None
    start_seconds_from_url: Callable[[str], int | None] | None = None

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
        seconds = (
            self.start_seconds_from_url(url) if self.start_seconds_from_url else None
        )
        return SchemeMatch(identifier=m.group(m.lastindex), start_seconds=seconds)

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
# the UI offers the stage at all — is the separate ``child_skips_locator``
# trait; a web child's stored locator stays legal, per the patch grammar.)
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
    normalize: Callable[[str], str | None] = _freeform_normalize
    parse_value: Callable[[str], int | None] | None = None
    format_value: Callable[[int], str] | None = None
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
      (its URL), so the cite flow skips the locator stage.
    - ``locator``: the type's locator contract (grammar, prompt, structured
      value bridge).
    - ``scheme_spec_type``: the spec class this type's schemes implement — the
      per-type Protocol (video schemes must be ``VideoSchemeSpec``, which
      requires ``deep_link``). The registry enforces it at import; mypy
      enforces it on each scheme module's constructor call.
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
