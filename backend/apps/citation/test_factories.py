"""Test-only factories for the citation-source family.

Kept outside ``tests/`` so test helpers can be imported across apps without
circular dependencies or duplicated conftest fixtures.

Use these instead of constructing the models directly. ``created_by`` /
``updated_by`` are non-null (``ActorAttributedModel``), so each factory stamps
:func:`default_actor` by default — encoding the attribution invariant in one
place so a forgotten actor can't slip into ``.objects.create``. Pass
``created_by=`` to attribute to a specific actor. Required FKs/fields default to
disposable values (mirroring ``make_machine_model``), so a bare
``make_citation_*()`` is a valid row.

The attribution fields are typed (``Actor``); the long-tail model fields ride
through ``**overrides`` typed by the model itself (its columns are the source of
truth — re-declaring them in a ``TypedDict`` here would only drift from it).
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.accounts.test_factories import default_actor
from apps.actors.models import Actor
from apps.citation.models import (
    CitationSource,
    CitationSourceLink,
    CitationSourceRootDomain,
)


def make_citation_source(
    *,
    name: str = "Test Citation Source",
    source_type: str = CitationSource.SourceType.WEB,
    created_by: Actor | None = None,
    updated_by: Actor | None = None,
    **overrides: Any,  # noqa: ANN401 - long-tail CitationSource fields, typed by the model.
) -> CitationSource:
    """Create a ``CitationSource`` for tests, defaulting name/source_type/actor."""
    created_by = created_by or default_actor()
    return CitationSource.objects.create(
        name=name,
        source_type=source_type,
        created_by=created_by,
        updated_by=updated_by or created_by,
        **overrides,
    )


def make_citation_link(
    *,
    citation_source: CitationSource | None = None,
    url: str | None = None,
    link_type: str = CitationSourceLink.LinkType.HOMEPAGE,
    created_by: Actor | None = None,
    updated_by: Actor | None = None,
    **overrides: Any,  # noqa: ANN401 - long-tail CitationSourceLink fields, typed by the model.
) -> CitationSourceLink:
    """Create a ``CitationSourceLink`` for tests, auto-providing a source and url."""
    created_by = created_by or default_actor()
    if url is None:  # default only when omitted — an explicit "" tests the constraint
        url = f"https://example.com/{uuid.uuid4().hex[:8]}"
    return CitationSourceLink.objects.create(
        citation_source=citation_source or make_citation_source(),
        url=url,
        link_type=link_type,
        created_by=created_by,
        updated_by=updated_by or created_by,
        **overrides,
    )


def make_citation_root_domain(
    *,
    source: CitationSource | None = None,
    host: str | None = None,
    created_by: Actor | None = None,
    updated_by: Actor | None = None,
    **overrides: Any,  # noqa: ANN401 - long-tail CitationSourceRootDomain fields, typed by the model.
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
        **overrides,
    )
