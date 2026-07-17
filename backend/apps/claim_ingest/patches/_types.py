"""Shared data carriers for the patch adapter (leaf module, no logic deps).

Only carriers used across *more than one* phase live here. A result type owned
by a single phase lives with its producer: emit's ``_RemovalResult`` /
``_MemberEmitResult`` / ``_HierarchyEdge`` in :mod:`.emit`, planning's
``_EntryResult`` / ``_TargetContribution`` / ``_TargetKey`` in :mod:`.planning`.
"""

from __future__ import annotations

from typing import NamedTuple

from django.db import models

from apps.claim_ingest.plan import Handle
from apps.core.types import ClaimSubjectId, ContentTypeId, PublicId


class PatchError(Exception):
    """A patch is malformed, unresolvable, or violates a guard.

    Raised before any write. The command turns it into a failed-run report.
    """


class _Target(NamedTuple):
    """Where a claim assertion lands: an existing entity or a planned handle."""

    content_type_id: ContentTypeId | None = None
    object_id: ClaimSubjectId | None = None
    handle: Handle | None = None


class _CreatedKey(NamedTuple):
    """Identity of an entity created earlier in the same patch.

    Keyed by the *resolved concrete model class* (never the ``entity_type``
    label), so a later reference looks it up by the FK/relationship target's
    ``related_model`` — the same class ``resolve_fk_target_pk`` queries — with
    no ``"corporate-entity"`` vs ``corporate_entity`` or base-vs-concrete drift.

    Typed ``type[models.Model]`` (not ``type[LinkableClaimModel]``) because
    lookups key by an FK target's ``related_model``, which Django only types as
    ``Model``; at runtime every catalog FK target *is* a ``LinkableClaimModel``.
    The key is pure identity, so the wider annotation costs nothing.
    """

    model_class: type[models.Model]
    public_id: PublicId
