"""Per-``SourceType`` facts the model reads, gathered into one table.

A dependency-free leaf (like ``hosts.py``): it owns ``SourceType`` and the
trait table but imports no app models, so ``models`` can import it one-way
without a cycle. ``CitationSource`` re-exports ``SourceType`` as
``CitationSource.SourceType`` so that stays the canonical, Django-idiomatic
handle.

The trait table is the single home for the facts that vary by source type, so
shared code reads a trait instead of branching on ``source_type == "web"`` (the
"branch on type in shared code" smell CLAUDE.md flags). Only facts live here,
never behavior: child *creation*, for one, keys on parent kind (scheme root vs
domain root), not source type, so it has no place in this table.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from django.db import models


class SourceType(models.TextChoices):
    BOOK = "book", "Book"
    MAGAZINE = "magazine", "Magazine"
    WEB = "web", "Web"


@dataclass(frozen=True, slots=True)
class SourceTypeTraits:
    """The per-source-type facts that shared code would otherwise branch on.

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

    flat_hierarchy: bool
    parentless_abstract: bool
    child_skips_locator: bool


SOURCE_TYPE_TRAITS: Final[Mapping[SourceType, SourceTypeTraits]] = {
    SourceType.BOOK: SourceTypeTraits(
        flat_hierarchy=False, parentless_abstract=False, child_skips_locator=False
    ),
    SourceType.MAGAZINE: SourceTypeTraits(
        flat_hierarchy=False, parentless_abstract=True, child_skips_locator=False
    ),
    SourceType.WEB: SourceTypeTraits(
        flat_hierarchy=True, parentless_abstract=True, child_skips_locator=True
    ),
}


def _assert_exhaustive_traits(
    registry: Mapping[SourceType, SourceTypeTraits],
) -> None:
    """Raise if any ``SourceType`` has no trait row.

    A helper (not a bare module-level ``assert``) so a test can call it directly
    against a deliberately-incomplete dict — no ``importlib.reload``. Called
    once at import below, so a new ``SourceType`` member without a row fails at
    load, not at the first runtime lookup.
    """
    missing = set(SourceType) - registry.keys()
    if missing:
        raise AssertionError(f"SourceType(s) missing a trait row: {sorted(missing)}")


_assert_exhaustive_traits(SOURCE_TYPE_TRAITS)


def source_type_traits(source_type: str | SourceType) -> SourceTypeTraits:
    """The traits for *source_type*, coercing a raw field value to ``SourceType``.

    The single typed chokepoint: callers pass a model's ``source_type``
    ``CharField`` (typed ``str``) and get the trait row back, with the coercion
    validating the value — an unknown string raises ``ValueError`` rather than a
    ``KeyError`` or a silent miss. Never index ``SOURCE_TYPE_TRAITS`` with a
    bare field value.
    """
    return SOURCE_TYPE_TRAITS[SourceType(source_type)]
