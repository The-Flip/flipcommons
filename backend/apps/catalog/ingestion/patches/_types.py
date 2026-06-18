"""Shared data carriers for the patch adapter (leaf module, no logic deps).

Only carriers used across *more than one* phase live here. A result type owned
by a single phase lives with its producer: emit's ``_RemovalResult`` /
``_MemberEmitResult`` / ``_HierarchyEdge`` in :mod:`.emit`, planning's
``_EntryResult`` / ``_TargetContribution`` / ``_TargetKey`` in :mod:`.planning`.
"""

from __future__ import annotations

from typing import NamedTuple

from django.db import models

from apps.catalog.ingestion.plan import Handle

# The composite key identifying one claim — a scalar/FK field name or a
# relationship member key from ``build_relationship_claim`` (e.g.
# ``"location:germany"``). A transparent alias of ``str``: it documents the
# concept where it recurs across the adapter without changing any interop with
# the ``str``-typed claim machinery (``apps.catalog.claims``, apply's ClaimIdentity).
type ClaimKey = str

# A catalog entity's public_id — the URL-identity value of its ``public_id_field``
# (``slug`` for most entities, ``location_path`` for Location), and what an FK or
# relationship member names its target by. A transparent alias of ``str`` like
# ``ClaimKey``: it distinguishes a public_id from the other ``str``s in the adapter
# (a handle/entry ``ref``, a relationship ``namespace``) at the points where the
# distinction is otherwise invisible — e.g. a ``dict[str, set[str]]`` adjacency map.
type PublicId = str


class PatchError(Exception):
    """A patch is malformed, unresolvable, or violates a guard.

    Raised before any write. The command turns it into a failed-run report.
    """


class _Target(NamedTuple):
    """Where a claim assertion lands: an existing entity or a planned handle."""

    content_type_id: int | None = None
    object_id: int | None = None
    handle: Handle | None = None


class _CreatedKey(NamedTuple):
    """Identity of an entity created earlier in the same patch.

    Keyed by the *resolved concrete model class* (never the ``entity_type``
    label), so a later reference looks it up by the FK/relationship target's
    ``related_model`` — the same class ``_lookup_pk`` queries — with no
    ``"corporate-entity"`` vs ``corporate_entity`` or base-vs-concrete drift.

    Typed ``type[models.Model]`` (not ``type[LinkableClaimModel]``) because
    lookups key by an FK target's ``related_model``, which Django only types as
    ``Model``; at runtime every catalog FK target *is* a ``LinkableClaimModel``.
    The key is pure identity, so the wider annotation costs nothing.
    """

    model_class: type[models.Model]
    public_id: PublicId
