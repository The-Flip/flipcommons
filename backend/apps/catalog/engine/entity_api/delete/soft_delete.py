"""Soft-delete execution and delete-API wire format for catalog entities.

A user "delete" in this system is a ``status=deleted`` claim at user priority
rather than a DB row removal. See ``docs/RecordLifecycle.md`` for the policy.

The generic cascade + PROTECT/usage-blocker walk lives in
``apps/core/soft_delete.py`` (a lifecycle utility over ``LifecycleStatusModel``,
knowing nothing of any concrete model). This module wraps that walk into the
catalog-typed shapes the delete API serializes — :class:`SoftDeletePlan` /
:class:`BlockingReferrer` — and executes the resulting ``status=deleted`` claims
(:func:`execute_soft_delete`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.db import models as db_models

from apps.claim_edit.claim_write import (
    ClaimSpec,
    EntityClaims,
    execute_multi_entity_claims,
)
from apps.core.models import is_live
from apps.core.soft_delete import CascadeBlocker, require_linkable, soft_delete_walk
from apps.provenance.models import (
    ChangeSet,
    ChangeSetAction,
    LinkableClaimModel,
    LinkableLifecycleClaimModel,
)
from apps.provenance.schemas import CitationReferenceInputSchema

from .schemas import BlockingReferrerSchema

_UserLike = AbstractBaseUser | AnonymousUser


@dataclass(frozen=True)
class BlockingReferrer:
    """A live reference that prevents a soft-delete from proceeding."""

    entity_type: str  # canonical hyphenated LinkableModel.entity_type, e.g. "model"
    pk: int
    name: str
    slug: str | None
    relation: str  # field name on the referring model (e.g. "variant_of")
    blocked_target_type: str  # which entity in the cascade the referrer points at
    blocked_target_slug: str | None


def serialize_blocking_referrer(ref: BlockingReferrer) -> BlockingReferrerSchema:
    """Wire format for :class:`BlockingReferrer` used by delete API responses."""
    return BlockingReferrerSchema(
        entity_type=ref.entity_type,
        slug=ref.slug,
        name=ref.name,
        relation=ref.relation,
        blocked_target_type=ref.blocked_target_type,
        blocked_target_slug=ref.blocked_target_slug,
    )


@dataclass
class SoftDeletePlan:
    """Outcome of :func:`plan_soft_delete`.

    If ``blockers`` is non-empty, the delete cannot proceed and the caller
    should surface them to the user. Otherwise ``entities_to_delete`` is the
    ordered list to receive ``status=deleted`` claims in a single ChangeSet.
    """

    entities_to_delete: list[LinkableLifecycleClaimModel] = field(default_factory=list)
    blockers: list[BlockingReferrer] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)


def _require_linkable_lifecycle(
    entity: db_models.Model,
) -> LinkableLifecycleClaimModel:
    """Narrow a core walk result to ``LinkableLifecycleClaimModel`` or raise.

    The core walk is typed on ``LifecycleStatusModel`` (the minimum the cascade
    algorithm needs); narrowing those members to ``LinkableLifecycleClaimModel``
    is a downcast — a bare ``LifecycleStatusModel`` is not statically linkable
    or claim-controlled. Every cascade member yielded for a catalog root is one
    at runtime, but the static bound is looser, so this boundary assert keeps
    :class:`SoftDeletePlan` honestly typed (consumers read claims and
    isinstance-test members) and fails loudly should the walk ever surface a
    lifecycle entity that isn't an addressable claim subject.
    """
    if not isinstance(entity, LinkableLifecycleClaimModel):
        raise TypeError(
            f"{type(entity).__name__} is not a LinkableLifecycleClaimModel; "
            "soft-delete plan requires addressable, claim-controlled lifecycle "
            "entities."
        )
    return entity


def _to_blocking_referrer(blocker: CascadeBlocker) -> BlockingReferrer:
    """Project a core :class:`CascadeBlocker` into the delete-API wire shape.

    Narrows both the referrer and the cascade member it pins to ``LinkableModel``
    (the same boundary assert the core walk defers to its callers) so the wire
    format carries canonical ``entity_type`` / ``slug`` rather than Django's
    concatenated ``_meta`` identity.
    """
    ref = require_linkable(blocker.referrer)
    target = require_linkable(blocker.blocked_target)
    return BlockingReferrer(
        entity_type=ref.entity_type,
        pk=ref.pk,
        name=str(ref),
        slug=getattr(ref, "slug", None),
        relation=blocker.relation,
        blocked_target_type=target.entity_type,
        blocked_target_slug=getattr(target, "slug", None),
    )


def plan_soft_delete(root: LinkableLifecycleClaimModel) -> SoftDeletePlan:
    """Plan a soft-delete of *root* plus every active cascade child.

    Wraps the generic :func:`apps.core.soft_delete.soft_delete_walk` into the
    typed plan the delete API serializes: the entities that would receive
    ``status=deleted`` claims and any active PROTECT or usage-M2M referrers
    that would block the delete.
    """
    walk = soft_delete_walk(root)
    return SoftDeletePlan(
        entities_to_delete=[_require_linkable_lifecycle(e) for e in walk.cascade],
        blockers=[_to_blocking_referrer(b) for b in walk.blockers],
    )


def count_entity_changesets(*entities: LinkableClaimModel) -> int:
    """Count distinct user ChangeSets with a claim on any of *entities*.

    Variadic so delete-preview endpoints can roll up provenance across a
    cascade (e.g. Title + its MachineModels) in a single distinct query —
    summing per-entity counts would double-count any ChangeSet that claims
    on more than one of them. With a single entity it collapses to the
    obvious one-entity query.
    """
    if not entities:
        return 0
    by_ct: dict[ContentType, list[int]] = {}
    for e in entities:
        ct = ContentType.objects.get_for_model(type(e))
        by_ct.setdefault(ct, []).append(e.pk)
    q = db_models.Q()
    for ct, pks in by_ct.items():
        q |= db_models.Q(claims__content_type=ct, claims__object_id__in=pks)
    return ChangeSet.objects.filter(user__isnull=False).filter(q).distinct().count()


class SoftDeleteBlockedError(Exception):
    """Raised by :func:`execute_soft_delete` when active references block it."""

    def __init__(self, blockers: list[BlockingReferrer]) -> None:
        self.blockers = blockers
        super().__init__(f"Blocked by {len(blockers)} active reference(s).")


def execute_soft_delete(
    root: LinkableLifecycleClaimModel,
    *,
    user: _UserLike,
    note: str = "",
    citation: CitationReferenceInputSchema | None = None,
) -> tuple[ChangeSet | None, list[LinkableLifecycleClaimModel]]:
    """Soft-delete *root* and all cascade children in one ChangeSet.

    Raises :class:`SoftDeleteBlockedError` when an active PROTECT referrer would
    be left dangling. Returns ``(changeset, entities_deleted)`` on success.
    """
    plan = plan_soft_delete(root)
    if plan.is_blocked:
        raise SoftDeleteBlockedError(plan.blockers)

    active_entities = [
        entity for entity in plan.entities_to_delete if is_live(entity.status)
    ]
    if not active_entities:
        # Entity is already soft-deleted; no-op.
        return None, []

    entries = [
        EntityClaims(entity, [ClaimSpec(field_name="status", value="deleted")])
        for entity in active_entities
    ]
    changeset = execute_multi_entity_claims(
        entries,
        user=user,
        action=ChangeSetAction.DELETE,
        note=note,
        citation=citation,
    )
    return changeset, active_entities
