"""Structural contracts for resolution resolvers — a dependency-free leaf.

Lives apart from :mod:`._dispatch` and :mod:`._relationships` so both can import
it without forming a module cycle: ``_relationships`` decorates its resolvers
with :func:`relationship_resolver`, while ``_dispatch`` types its dispatch table
on :class:`RelationshipResolver`. This module imports nothing from the package.
"""

from __future__ import annotations

from typing import Protocol


class RelationshipResolver(Protocol):
    """Structural contract for a bulk relationship resolver.

    Every ``resolve_all_*`` resolver takes the canonical ``subject_ids`` kwarg
    and writes its through-rows for that subject set (or all subjects when
    ``None``). Pinned on each implementation via the ``@relationship_resolver``
    no-op decorator so signature drift is flagged at the function, not only at
    the dispatch-table assignment.
    """

    def __call__(self, *, subject_ids: set[int] | None = None) -> None: ...


def relationship_resolver(fn: RelationshipResolver) -> RelationshipResolver:
    """No-op decorator pinning a resolver to the ``RelationshipResolver`` contract."""
    return fn
