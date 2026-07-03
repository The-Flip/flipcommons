"""Core contracts for citation-type and scheme plugins.

A dependency-free leaf (like ``hosts.py``): it owns ``SourceType`` and the
spec dataclasses but imports no app models, so ``models`` can import it
one-way without a cycle. ``CitationSource`` re-exports ``SourceType`` as
``CitationSource.SourceType`` so that stays the canonical, Django-idiomatic
handle.

Two plugin units live behind these contracts (see
``docs/plans/citations/VideoCitations.md``):

- A **citation type** (:class:`CitationTypeSpec`) — book, magazine, web —
  owns the per-type behavior shared code would otherwise branch on: hierarchy
  shape, abstractness, locator handling.
- A **scheme** (:class:`SchemeSpec`) — ipdb, opdb, youtube — owns one
  platform's URL recognition: how to pull an identifier out of any of the
  platform's URL shapes, validate a bare identifier, and build the canonical
  URL every shape collapses to. A scheme belongs to exactly one citation type
  (``source_type``), which is what its children mint as.

Specs are **pure**: declarative facts plus stateless functions. No model
imports, no DB access, no I/O — all DB work (child minting, recognition
queries, instance writes) stays in core code that consumes these specs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from django.db import models


class SourceType(models.TextChoices):
    BOOK = "book", "Book"
    MAGAZINE = "magazine", "Magazine"
    WEB = "web", "Web"


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
    """

    source_type: SourceType
    flat_hierarchy: bool
    parentless_abstract: bool
    child_skips_locator: bool

    @property
    def label(self) -> str:
        """The human-facing type label (the ``SourceType`` choice label)."""
        return self.source_type.label


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
    its root is seeded — but the patch is authored from these facts, and
    conformance checks assert spec and seed can't silently disagree.
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

    - ``url_pattern`` captures the identifier as **group 1** and is anchored on
      ``https?://<host>`` so a look-alike host (``notyoutube.com``) can't match.
    - ``id_pattern`` fullmatches a bare identifier.
    - ``canonical_url`` builds the one URL every shape collapses to —
      ``extract(canonical_url(id))`` must round-trip.
    - ``example_identifier`` is a real, well-formed identifier; it seeds the
      harness's round-trip checks and doubles as documentation.
    """

    key: str
    label: str
    source_type: SourceType
    url_pattern: re.Pattern[str]
    id_pattern: re.Pattern[str]
    canonical_url: Callable[[str], str]
    example_identifier: str
    root_seed: RootSeed

    def extract(self, url: str) -> SchemeMatch | None:
        """Recognize *url* as one of this scheme's shapes, or ``None``."""
        m = self.url_pattern.search(url)
        if m is None:
            return None
        return SchemeMatch(identifier=m.group(1))

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
