"""``ActorModel``: the abstract base every actor-backing model inherits.

Inherited *downward* by satellites that live in higher app tiers — ``User``
(accounts) and ``Source`` (provenance). ``apps.actors`` therefore must never
import those classes; the registry discovers them via ``__subclasses__()`` at
runtime (Django has imported every model by app-ready). Same direction as
``LinkableModel`` / ``core.entity_types``.

The base owns the mint-on-create + sync-on-update of the backing record's
``Actor`` row, deriving the resolution fields from per-instance hooks each
satellite implements. The hooks read the satellite's legacy ``priority`` /
``is_enabled`` columns, making ``Actor`` a continuously-correct mirror of them
throughout the transition (see ``docs/plans/auth/Actors.md`` § "Why mint *and*
sync"). The hooks retire when "Drop dead schema" removes those columns.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import models, transaction

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
        # null=False (the default) is the FINAL shipped state. The transitional
        # nullability lives ONLY in the staged migration (AddField null=True ->
        # RunPython mint -> AlterField null=False). The model never says null=True.
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
                # UPDATE: keep the mirror in sync with the legacy columns.
                # .update() (not .save()) avoids re-entering this method.
                Actor.objects.filter(pk=self.actor_id).update(
                    priority=self.actor_priority,
                    resolution_status=self.actor_resolution_status,
                )

    # --- Mirror hooks -------------------------------------------------------
    # INVARIANT (transition window): the legacy columns these read
    # (User.priority, Source.priority / is_enabled) may be written ONLY via
    # save(). The mirror is maintained in save() above, so QuerySet.update() /
    # bulk_update() bypass it and silently desync the Actor. Don't bulk-mutate a
    # mirrored field without re-syncing its Actor — it would break the later
    # cutover's byte-identical-resolution guarantee. (Regression-pinned in
    # tests/test_actor_sync.py::test_queryset_update_bypasses_mirror.)
    @property
    def actor_priority(self) -> int:
        """Priority for this instance's Actor. Subclass returns its legacy column."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement actor_priority"
        )

    @property
    def actor_resolution_status(self) -> ActorResolutionStatus:
        """Resolution status for this instance's Actor. Subclass derives it."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement actor_resolution_status"
        )
