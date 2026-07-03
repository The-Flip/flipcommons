"""Test-only factories for the citation-source family.

Kept outside ``tests/`` so test helpers can be imported across apps without
circular dependencies or duplicated conftest fixtures.

Use these instead of constructing the models directly. ``created_by`` /
``updated_by`` are non-null (``ActorAttributedModel``), so each factory stamps
:func:`default_actor` by default — encoding the attribution invariant in one
place so a forgotten actor can't slip into ``.objects.create``. Pass
``created_by=`` to attribute to a specific actor. Required FKs/fields default to
disposable values, so a bare ``make_citation_*()`` is a valid row.

Every column is an explicit, typed keyword with a default, so a mistyped kwarg
fails at type-check rather than at ``.objects.create`` runtime.
"""

from __future__ import annotations

import uuid
from typing import Literal

from apps.accounts.test_factories import default_actor
from apps.actors.models import Actor
from apps.citation.citation_types import CitationSourceTypeValue
from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)

# CitationSourceTypeValue is the canonical wire Literal (citation_types);
# the remaining aliases mirror each model's choices, so a bad choice value fails at
# type-check. Constraint tests that need an invalid value build the model
# directly. ``identifier_key`` also permits "" (blank = a root without a scheme).
type LinkTypeValue = Literal["homepage", "catalog", "publisher", "reference", "archive"]
type IdentifierKeyValue = Literal["", "ipdb", "opdb", "youtube"]


def make_citation_source(
    *,
    name: str = "Test Citation Source",
    source_type: CitationSourceTypeValue = "web",
    author: str = "",
    publisher: str = "",
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    date_note: str = "",
    isbn: str | None = None,
    parent: CitationSource | None = None,
    description: str = "",
    identifier_key: IdentifierKeyValue = "",
    identifier: str = "",
    created_by: Actor | None = None,
    updated_by: Actor | None = None,
) -> CitationSource:
    """Create a ``CitationSource`` for tests, defaulting name/source_type/actor."""
    created_by = created_by or default_actor()
    return CitationSource.objects.create(
        name=name,
        source_type=source_type,
        author=author,
        publisher=publisher,
        year=year,
        month=month,
        day=day,
        date_note=date_note,
        isbn=isbn,
        parent=parent,
        description=description,
        identifier_key=identifier_key,
        identifier=identifier,
        created_by=created_by,
        updated_by=updated_by or created_by,
    )


def make_citation_link(
    *,
    citation_source: CitationSource | None = None,
    url: str | None = None,
    link_type: LinkTypeValue = "homepage",
    label: str = "",
    created_by: Actor | None = None,
    updated_by: Actor | None = None,
) -> CitationSourceLink:
    """Create a ``CitationSourceLink`` for tests, auto-providing a source and url."""
    created_by = created_by or default_actor()
    if url is None:  # default only when omitted — an explicit "" tests the constraint
        url = f"https://example.com/{uuid.uuid4().hex[:8]}"
    return CitationSourceLink.objects.create(
        citation_source=citation_source or make_citation_source(),
        url=url,
        link_type=link_type,
        label=label,
        created_by=created_by,
        updated_by=updated_by or created_by,
    )


def make_citation_root_domain(
    *,
    source: CitationSource | None = None,
    host: str | None = None,
    created_by: Actor | None = None,
    updated_by: Actor | None = None,
) -> CitationSourceRootDomain:
    """Create a ``CitationSourceRootDomain`` for tests, auto-providing a root and host."""
    created_by = created_by or default_actor()
    if host is None:  # default only when omitted — an explicit "" tests the constraint
        host = f"example-{uuid.uuid4().hex[:8]}.com"
    return CitationSourceRootDomain.objects.create(
        source=source or make_citation_source(),
        host=host,
        created_by=created_by,
        updated_by=updated_by or created_by,
    )
