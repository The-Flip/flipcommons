"""Provenance activity rules."""

from __future__ import annotations

from typing import Protocol

from apps.core.authz.predicates import email_verified, is_active, is_authenticated
from apps.core.authz.registry import register
from apps.core.authz.types import (
    Activity,
    Allow,
    Decision,
    DenialCode,
    Deny,
    PolicyContext,
    PolicyUser,
)


class ChangeSetPolicyView(Protocol):
    """Attribute surface ``is_changeset_author`` may read off a ChangeSet.

    Declared as read-only ``@property`` so mypy treats the predicate as
    type-checked against this narrow shape — any reach for an attribute
    outside this Protocol (e.g. ``changeset.actor.user``) is a static
    error at predicate-definition time, which is what keeps the no-I/O
    discipline honest. ``actor_id`` is a plain FK column (always loaded), so
    the predicate needs no join or ``select_related``.
    """

    @property
    def id(self) -> int: ...

    @property
    def actor_id(self) -> int | None: ...


def is_changeset_author(
    user: PolicyUser,
    changeset: ChangeSetPolicyView,
    context: PolicyContext | None,
) -> Decision:
    """Allow when the caller authored ``changeset``; else ``OWNER_REQUIRED``.

    Compares the actor FK columns directly: a changeset is the caller's iff its
    actor is the caller's actor. Both sides are plain columns (no I/O). For an
    anonymous caller ``user.actor_id`` is ``None`` (patched onto AnonymousUser)
    and never equals a changeset's non-null actor, so the result is a denial;
    ``is_authenticated`` supplies the higher-priority ``AUTH_REQUIRED``.

    The defensive ``changeset is None`` guard lives in the evaluator
    (``check()``), not here — any target-aware rule called without a
    target raises ``TypeError`` before reaching its predicates.
    """
    if changeset.actor_id != user.actor_id:
        return Deny(DenialCode.OWNER_REQUIRED)
    return Allow()


register(
    Activity.CLAIM_REVERT,
    is_authenticated,
    is_active,
    email_verified,
    target_aware=True,
)
register(
    Activity.CHANGESET_UNDO,
    is_authenticated,
    is_active,
    email_verified,
    is_changeset_author,
    target_aware=True,
    target=ChangeSetPolicyView,
)
