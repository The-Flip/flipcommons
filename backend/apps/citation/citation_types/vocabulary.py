"""Shared vocabulary for the citation plugin system.

The bottom leaf both plugin axes build on — and the only thing they share
besides the composition seam: the source-type enum, its typed Literal twin
and the semantic aliases. No declarations, no framework machinery, no
imports from the package.

``CitationSource`` re-exports ``SourceType`` as ``CitationSource.SourceType``
so that stays the canonical, Django-idiomatic handle for model code.
"""

from __future__ import annotations

from typing import Literal, TypeGuard, get_args

from django.db import models

# Semantic aliases (intent only, no checker safety — the ``Slug = str``
# pattern from docs/Python.md). ``SchemeKey`` is a scheme's ``identifier_key``
# value ("youtube"); ``StartSeconds`` is a video start position in whole
# seconds — the one structured locator value that currently exists, shared by
# the locator bridge (parse/format) and scheme deep links so the "type owns
# the value, scheme consumes it" symmetry is visible in the signatures.
SchemeKey = str
StartSeconds = int

# The reserved left segment of an ``isbn:`` patch cite ref. Deliberately NOT a
# registered scheme — a scheme is a platform whose root mints children from
# URLs, while a book is its own root and is never minted by a cite — but it
# shares the ``<prefix>:<identifier>`` cite namespace with scheme keys and
# authored root slugs. Owned here (the dependency-free leaf) so the model's
# reserved-handle constraint and the patch parser derive from one constant
# without inverting the citation ← claim_ingest boundary.
ISBN_CITE_PREFIX = "isbn"


class SourceType(models.TextChoices):
    BOOK = "book", "Book"
    PERIODICAL = "periodical", "Periodical"
    WEB = "web", "Web"
    VIDEO = "video", "Video"


# The Literal twin of ``SourceType``, for **internal** Python contracts
# (TypedDicts, test factories, helper signatures). Deliberately NOT used on
# Ninja ``Schema`` fields — wire scalars stay bare ``str`` per
# ``docs/Python.md`` so internal renames never surface as schema diffs. A
# Literal can't be derived from the enum, so the import-time assertion below
# keeps the hand-mirrored list honest.
CitationSourceTypeValue = Literal["book", "periodical", "web", "video"]


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
