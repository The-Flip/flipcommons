"""Soft-delete planning and execution for user-deletable catalog entities.

A user "delete" in this system is a ``status=deleted`` claim at user priority
rather than a DB row removal. See ``docs/RecordLifecycle.md`` for the policy.
The walker below enforces these cascade rules:

* CASCADE to an independent lifecycle entity — write ``status=deleted``
  claims for each active child in the same ChangeSet. Modeled here by an
  opt-in ``soft_delete_cascade_relations`` attribute on the parent model,
  because the DB FK may itself be PROTECT (e.g. ``MachineModel.title``).
* CASCADE to an owned child row with no lifecycle — do nothing. The child
  rides with the parent's visibility.
* PROTECT, referenced by an active independent entity — block. The user
  must resolve the reference before the delete can proceed.
* PROTECT, referenced only by soft-deleted (or non-lifecycle) entities —
  allow. The DB-level PROTECT stays as a safety net against hard deletes;
  this rule is enforced here, at the application layer, because the DB
  can't see ``status=deleted``.

The walker is generic over any entity with ``LifecycleStatusModel``. Title is
the first caller; Model Delete and the rest will plug in by declaring
``soft_delete_cascade_relations`` on their models.

Some lifecycle references aren't visible through the reverse-FK pass: M2M
through-rows (``MachineModelTag``, ``MachineModelTheme``, …) and
self-referential hierarchy (``Theme.parents``, ``GameplayFeature.parents``)
hop through an intermediate table that itself has no lifecycle. Models
that care about those "usage" references declare them explicitly via
``soft_delete_usage_blockers``, a frozenset of reverse-manager names to walk
for active referrers — closing the gap between "no FK PROTECT breakage
at the DB" and "no active lifecycle entity still references me at the
application layer".
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple, TypeGuard

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.db import models as db_models

from apps.catalog.models import CatalogModel
from apps.core.models import LifecycleStatusModel, is_live
from apps.provenance.models import ChangeSet, ChangeSetAction
from apps.provenance.schemas import CitationReferenceInputSchema

from .edit_claims import ClaimSpec, execute_multi_entity_claims
from .schemas import BlockingReferrerSchema

_UserLike = AbstractBaseUser | AnonymousUser


class EntityKey(NamedTuple):
    """Dedup key for a soft-delete cascade member or blocker.

    ``label_lower`` (``app_label.model_name``) plus ``pk`` uniquely
    identifies a row across the heterogeneous set of models the walker
    touches.
    """

    label_lower: str
    pk: int


@dataclass(frozen=True)
class BlockingReferrer:
    """A live reference that prevents a soft-delete from proceeding."""

    entity_type: str  # canonical hyphenated CatalogModel.entity_type, e.g. "model"
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

    entities_to_delete: list[CatalogModel] = field(default_factory=list)
    blockers: list[BlockingReferrer] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)


def _has_status(
    model_class: type[db_models.Model],
) -> TypeGuard[type[LifecycleStatusModel]]:
    return issubclass(model_class, LifecycleStatusModel)


def _entity_type(entity: db_models.Model) -> str:
    """Canonical hyphenated entity_type for wire-format serialization.

    Roots reach this only as ``CatalogModel`` (statically enforced by the
    walker's signatures). Blockers, however, come from the iterators as
    ``db_models.Model`` — those need the runtime ``CatalogModel`` check so
    we don't silently leak Django's concatenated ``_meta.model_name`` into
    the wire format. If the iterators ever start yielding non-CatalogModel
    referrers, add an explicit policy here.
    """
    cls = type(entity)
    if not issubclass(cls, CatalogModel):
        raise TypeError(
            f"{cls.__name__} is not a CatalogModel; soft-delete wire format "
            "requires a canonical entity_type."
        )
    return cls.entity_type


def _entity_key(entity: db_models.Model) -> EntityKey:
    return EntityKey(entity._meta.label_lower, entity.pk)


def _cascade_targets(root: CatalogModel) -> list[CatalogModel]:
    """Walk ``soft_delete_cascade_relations`` to produce the ordered cascade.

    Deterministic order (parent before children, siblings by pk) so the
    resulting ChangeSet replays identically in tests.
    """
    result: list[CatalogModel] = []
    seen: set[EntityKey] = set()
    stack: list[CatalogModel] = [root]
    while stack:
        entity = stack.pop(0)
        key = _entity_key(entity)
        if key in seen:
            continue
        seen.add(key)
        result.append(entity)
        for rel_name in type(entity).soft_delete_cascade_relations:
            manager = getattr(entity, rel_name)
            qs = manager.active().order_by("pk")
            stack.extend(qs)
    return result


def _iter_protect_referrers(
    entity: CatalogModel,
) -> Iterator[tuple[db_models.Model, str]]:
    """Yield ``(referrer, relation_name)`` for active PROTECT referrers.

    Only referrers whose model has ``LifecycleStatusModel`` count — PROTECT
    pointers from owned child rows (aliases, through tables, abbreviations)
    are ignored for soft-delete purposes (they ride with the parent).
    """
    for rel in type(entity)._meta.get_fields():
        if not rel.auto_created:
            continue
        if not (rel.one_to_many or rel.one_to_one):
            continue
        # One/many-to-one auto-created = ForeignObjectRel carrying the
        # remote ForeignKey via ``.field``.
        assert isinstance(rel, db_models.ForeignObjectRel)
        remote_field = rel.field  # ForeignKey on the remote model
        on_delete = remote_field.remote_field.on_delete
        if on_delete is db_models.PROTECT:
            remote_model = rel.related_model
            assert isinstance(remote_model, type)
            assert issubclass(remote_model, db_models.Model)
            if not _has_status(remote_model):
                continue
            fk_name = remote_field.name
            qs = remote_model.objects.active().filter(**{fk_name: entity})
            for ref in qs:
                yield ref, fk_name
        elif on_delete in (db_models.SET_NULL, db_models.SET_DEFAULT):
            raise NotImplementedError(
                f"SET_NULL / SET_DEFAULT on {type(entity).__name__}.{rel.name} "
                "is not handled by the soft-delete walker. Add an explicit "
                "policy before enabling delete on a model with this relation."
            )
        # CASCADE branches are intentionally silent here: either the remote
        # model is in soft_delete_cascade_relations (handled elsewhere) or
        # it's an owned child that rides with parent visibility.


def _iter_usage_blockers(
    entity: CatalogModel,
) -> Iterator[tuple[db_models.Model, str]]:
    """Yield ``(referrer, manager_name)`` for active referrers reachable via
    ``soft_delete_usage_blockers`` — M2M through-rows and self-ref hierarchy.

    Each manager name must resolve to a reverse manager that supports
    ``.active()`` (i.e. whose remote model is a ``LifecycleQuerySet`` user,
    via ``LifecycleStatusModel``). Yielded referrers are always active.
    """
    for manager_name in type(entity).soft_delete_usage_blockers:
        manager = getattr(entity, manager_name)
        for ref in manager.active():
            yield ref, manager_name


def plan_soft_delete(root: CatalogModel) -> SoftDeletePlan:
    """Plan a soft-delete of *root* plus every active cascade child.

    Returns both the entities that would receive ``status=deleted`` claims
    and any active PROTECT or usage-M2M referrers that would block the
    delete.
    """
    cascade = _cascade_targets(root)
    cascade_keys = {_entity_key(e) for e in cascade}

    blockers: list[BlockingReferrer] = []
    seen_blockers: set[tuple[EntityKey, str]] = set()

    def _record(ref: db_models.Model, relation: str, target: CatalogModel) -> None:
        key = (_entity_key(ref), relation)
        if key in seen_blockers:
            return
        seen_blockers.add(key)
        blockers.append(
            BlockingReferrer(
                entity_type=_entity_type(ref),
                pk=ref.pk,
                name=str(ref),
                slug=getattr(ref, "slug", None),
                relation=relation,
                blocked_target_type=_entity_type(target),
                blocked_target_slug=getattr(target, "slug", None),
            )
        )

    for entity in cascade:
        for ref, relation in _iter_protect_referrers(entity):
            if _entity_key(ref) in cascade_keys:
                continue
            _record(ref, relation, entity)
        for ref, manager_name in _iter_usage_blockers(entity):
            if _entity_key(ref) in cascade_keys:
                continue
            _record(ref, manager_name, entity)

    return SoftDeletePlan(entities_to_delete=cascade, blockers=blockers)


def count_entity_changesets(*entities: CatalogModel) -> int:
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
    root: CatalogModel,
    *,
    user: _UserLike,
    note: str = "",
    citation: CitationReferenceInputSchema | None = None,
) -> tuple[ChangeSet | None, list[CatalogModel]]:
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
        (entity, [ClaimSpec(field_name="status", value="deleted")])
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
