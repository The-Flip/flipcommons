"""``ActorModel``: the abstract base every actor-backing model inherits.

Inherited *downward* by satellites that live in higher app tiers — ``User``
(accounts) and ``Source`` (provenance). ``apps.actors`` therefore must never
import those classes; the registry discovers them via ``__subclasses__()`` at
runtime (Django has imported every model by app-ready). Same direction as
``LinkableModel`` / ``core.entity_types``.

The base owns the mint-on-create + sync-on-update of the backing record's
``Actor`` row, deriving the resolution fields from per-instance hooks each
satellite implements. The hooks read the satellite's editable ``priority`` /
``is_enabled`` columns, making ``Actor`` a continuously-correct mirror of them.
This mirror is permanent: the satellite columns are the per-type editing surface
and Actor is the uniform resolution read-model.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import models, transaction
from django.db.models.signals import pre_delete

from .actor import Actor, ActorResolutionStatus


class ActorModel(models.Model):
    """A model whose instances are attributable actors.

    Concrete subclasses MUST declare ``is_machine`` and override
    ``actor_priority`` / ``actor_resolution_status`` (enforced by the
    ``actors`` system check). The base wires the ``actor`` OneToOne and the
    mint/sync lifecycle generically — no per-type branching.
    """

    # Whether this actor type is a machine (vs a human). Class-level, derived
    # per type (User=False, Source=True); never stored on Actor.
    is_machine: ClassVar[bool]

    # Django sets this descriptor; declared for strong typing of the save() path.
    actor_id: int | None

    actor = models.OneToOneField(
        "actors.Actor",
        on_delete=models.PROTECT,  # Actor outlives the backing record
        related_name="%(class)s",  # -> Actor.user / Actor.source
        editable=False,  # mint-managed; never a form field (keeps it out of admin)
        # null=False is the shipped model state; historical migrations handled
        # the temporary nullable window needed to backfill existing rows.
    )

    class Meta:
        abstract = True

    # Django's Model.save signature is owned by the framework; the override only
    # adds Actor mint-on-create and sync-on-update around the upstream call.
    def save(
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        creating = self._state.adding
        with transaction.atomic():
            if creating and self.actor_id is None:
                # CREATE: mint the Actor from the instance hooks, then link it.
                self.actor = Actor.objects.create(
                    backing_model=self._meta.model_name,
                    priority=self.actor_priority,
                    resolution_status=self.actor_resolution_status,
                )
            super().save(*args, **kwargs)
            if not creating and self.actor_id is not None:
                # UPDATE: keep the Actor mirror in sync with backing fields.
                # .update() (not .save()) avoids re-entering this method.
                Actor.objects.filter(pk=self.actor_id).update(
                    priority=self.actor_priority,
                    resolution_status=self.actor_resolution_status,
                )

    # --- Mirror hooks -------------------------------------------------------
    # PERMANENT INVARIANT: the columns these read (User.priority,
    # Source.priority / is_enabled) may be written ONLY via save(). The mirror is
    # maintained in save() above, so QuerySet.update() / bulk_update() bypass it
    # and silently desync the Actor — e.g. Source.objects.update(is_enabled=False)
    # would leave Actor.resolution_status stale and break the kill switch. Don't
    # bulk-mutate a mirrored field without re-syncing its Actor. (Regression-pinned
    # in tests/test_actor_sync.py::test_queryset_update_bypasses_mirror.)
    @property
    def actor_priority(self) -> int:
        """Priority for this instance's Actor. Subclass returns its column."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement actor_priority"
        )

    @property
    def actor_resolution_status(self) -> ActorResolutionStatus:
        """Resolution status for this instance's Actor. Subclass derives it."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement actor_resolution_status"
        )


def _protect_backing_with_history(
    sender: type[ActorModel],
    instance: ActorModel,
    **kwargs: Any,  # noqa: ANN401  # Django signal-handler signature
) -> None:
    """Block deleting a backing record whose Actor has attributed history.

    Deletion protection now lives uniformly on the Actor, replacing the old
    per-backing-record history FKs. ``claims`` / ``changesets`` are the reverse
    ``related_name``s Claim / ChangeSet declare on Actor — runtime attribute
    access, so ``apps.actors`` stays a leaf below ``provenance`` (no upward
    import).

    Connected as ``pre_delete`` (not a ``Model.delete()`` override) so it fires
    on ``QuerySet.delete()`` too — registering a listener disables Django's
    fast-delete path. NOTE: this is ORM-level only; raw SQL bypasses it. The
    Actor's own history stays DB-protected by ``Claim.actor`` / ``ChangeSet.actor``
    PROTECT regardless.
    """
    _ = sender, kwargs
    if instance.actor_id is None:
        return
    actor = instance.actor
    if not (actor.claims.exists() or actor.changesets.exists()):
        return
    protected: set[models.Model] = {
        *actor.claims.all()[:1],
        *actor.changesets.all()[:1],
    }
    raise models.ProtectedError(
        f"Cannot delete {type(instance).__name__} #{instance.pk}: its actor "
        "has attributed history (claims or changesets).",
        protected,
    )


def connect_delete_guards() -> None:
    """Wire :func:`_protect_backing_with_history` to every concrete ActorModel.

    Called from ``ActorsConfig.ready()``. Connecting per concrete subclass
    (rather than ``sender=None``) keeps Django's fast-delete path enabled for
    every unrelated model. Walks ``__subclasses__()`` — the same registry walk
    as ``apps.actors.checks`` — so new actor types are covered automatically.
    """
    seen: set[type] = set()

    def walk(cls: type[ActorModel]) -> None:
        for subclass in cls.__subclasses__():
            if subclass in seen:
                continue
            seen.add(subclass)
            walk(subclass)
            meta = getattr(subclass, "_meta", None)
            if meta is None or meta.abstract:
                continue
            pre_delete.connect(
                _protect_backing_with_history,
                sender=subclass,
                dispatch_uid=f"actors.protect_backing.{meta.label}",
            )

    walk(ActorModel)  # type: ignore[type-abstract]
