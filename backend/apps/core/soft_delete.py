"""Generic soft-delete cascade walk over ``LifecycleStatusModel``.

A user "delete" in this system is a ``status=deleted`` claim at user priority
rather than a DB row removal. See ``docs/RecordLifecycle.md`` for the policy.
This module owns the *introspection* half — discovering the cascade and the
references that block it — with no knowledge of any concrete domain model. The
*execution* half (writing the ``status=deleted`` claims) and the delete-API wire
format live in ``apps/catalog/api/soft_delete.py``, which wraps this walk.

The walker enforces these cascade rules:

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

The walker is generic over every concrete ``LifecycleStatusModel``: each model
declares its own cascade relations (``soft_delete_cascade_relations``) and usage
blockers (``soft_delete_usage_blockers``). That every inbound reference is
classified — so the walk can't silently miss a blocker — is enforced at boot by
``check_soft_delete_policy`` in ``core/checks.py``.

Some lifecycle references aren't visible through the reverse-FK pass: M2M
through-rows (``MachineModelTag``, ``MachineModelTheme``, …) and
self-referential hierarchy (``Theme.parents``, ``GameplayFeature.parents``)
hop through an intermediate table that itself has no lifecycle. Models
that care about those "usage" references declare them explicitly via
``soft_delete_usage_blockers``, a frozenset of reverse-manager names to walk
for active referrers — closing the gap between "no FK PROTECT breakage
at the DB" and "no active lifecycle entity still references me at the
application layer".

The walk returns raw ``LifecycleStatusModel`` instances — the minimum bound the
algorithm needs. Reading display identity (``entity_type``, ``public_id``,
``slug``) off a result is the caller's job: narrow with :func:`require_linkable`
at the use site, the same boundary assert the catalog wrapper makes before
serializing a blocker to the wire.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple, TypeGuard

from django.db import models as db_models

from apps.core.models import LifecycleStatusModel, LinkableModel


def has_lifecycle(
    model_class: type[db_models.Model],
) -> TypeGuard[type[LifecycleStatusModel]]:
    """Narrow *model_class* to a lifecycle model (has ``status`` / ``.active()``).

    A ``TypeGuard`` so a ``True`` result statically narrows the model class to
    ``type[LifecycleStatusModel]`` at the call site — used both by the walk's
    own reverse-FK pass and by the patch front end's lifecycle-dependent gates
    (``delete:`` routing) to make the optional lifecycle capability visible to
    the type checker rather than stringly-checked.
    """
    return issubclass(model_class, LifecycleStatusModel)


def require_linkable(entity: db_models.Model) -> LinkableModel:
    """Narrow a walk result to ``LinkableModel`` or raise.

    The walk yields ``LifecycleStatusModel`` instances; reading ``entity_type``
    / ``public_id`` / a canonical identifier requires linkability. Every site
    that formats a cascade member or blocker for display narrows through here, so
    the impossible non-linkable case fails loudly in one place instead of leaking
    Django's concatenated ``_meta`` identity into a public surface.
    """
    if not isinstance(entity, LinkableModel):
        raise TypeError(
            f"{type(entity).__name__} is not a LinkableModel; soft-delete "
            "display requires a canonical addressing scheme."
        )
    return entity


class _CascadeKey(NamedTuple):
    """Dedup key for a soft-delete cascade member or blocker.

    ``label_lower`` (``app_label.model_name``) plus ``pk`` uniquely
    identifies a row across the heterogeneous set of models the walker
    touches. Private, and named distinctly from ``core.types.EntityKey``
    (``content_type_id, object_id``) — a different shape that ingest spreads
    into claim targets — so the two never collide.
    """

    label_lower: str
    pk: int


class CascadeBlocker(NamedTuple):
    """A live reference that prevents a soft-delete from proceeding.

    Keeps the raw ``(referrer, relation, blocked_target)`` triple as
    ``LifecycleStatusModel`` instances — preserving *which* cascade member the
    referrer pins — without reading identity off either, so the bound assumes no
    linkability. Callers narrow via :func:`require_linkable` to format it.
    """

    referrer: LifecycleStatusModel
    relation: str  # field/manager name on the referring model (e.g. "variant_of")
    blocked_target: LifecycleStatusModel


class SoftDeleteWalk(NamedTuple):
    """Outcome of :func:`soft_delete_walk`.

    ``cascade`` is the ordered list of entities that would receive
    ``status=deleted`` claims. ``blockers`` is the active references that would
    be left dangling — non-empty means the delete cannot proceed.
    """

    cascade: list[LifecycleStatusModel]
    blockers: list[CascadeBlocker]


def _cascade_key(entity: db_models.Model) -> _CascadeKey:
    return _CascadeKey(entity._meta.label_lower, entity.pk)


def cascade_targets(root: LifecycleStatusModel) -> list[LifecycleStatusModel]:
    """Walk ``soft_delete_cascade_relations`` to produce the ordered cascade.

    Deterministic order (parent before children, siblings by pk) so the
    resulting ChangeSet replays identically in tests. Cheaper than
    :func:`soft_delete_walk` — it skips the blocker enumeration — for callers
    that need only the delete footprint.
    """
    result: list[LifecycleStatusModel] = []
    seen: set[_CascadeKey] = set()
    stack: list[LifecycleStatusModel] = [root]
    while stack:
        entity = stack.pop(0)
        key = _cascade_key(entity)
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
    entity: LifecycleStatusModel,
) -> Iterator[tuple[LifecycleStatusModel, str]]:
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
            if not has_lifecycle(remote_model):
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
    entity: LifecycleStatusModel,
) -> Iterator[tuple[LifecycleStatusModel, str]]:
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


def soft_delete_walk(root: LifecycleStatusModel) -> SoftDeleteWalk:
    """Plan a soft-delete of *root* plus every active cascade child.

    Returns both the entities that would receive ``status=deleted`` claims
    and any active PROTECT or usage-M2M referrers that would block the
    delete.
    """
    cascade = cascade_targets(root)
    cascade_keys = {_cascade_key(e) for e in cascade}

    blockers: list[CascadeBlocker] = []
    seen_blockers: set[tuple[_CascadeKey, str]] = set()

    def _record(
        ref: LifecycleStatusModel, relation: str, target: LifecycleStatusModel
    ) -> None:
        key = (_cascade_key(ref), relation)
        if key in seen_blockers:
            return
        seen_blockers.add(key)
        blockers.append(
            CascadeBlocker(referrer=ref, relation=relation, blocked_target=target)
        )

    for entity in cascade:
        for ref, relation in _iter_protect_referrers(entity):
            if _cascade_key(ref) in cascade_keys:
                continue
            _record(ref, relation, entity)
        for ref, manager_name in _iter_usage_blockers(entity):
            if _cascade_key(ref) in cascade_keys:
                continue
            _record(ref, manager_name, entity)

    return SoftDeleteWalk(cascade=cascade, blockers=blockers)
