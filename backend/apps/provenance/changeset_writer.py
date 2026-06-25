"""The actor-first ChangeSet funnel, ``record_changeset``.

Every interactive (user) ChangeSet is minted here, so attribution is set in
exactly one place: ``actor`` is always populated. Interactive edits are
distinguished from ingest batches by ``ingest_run IS NULL`` (the DB
``action IFF ingest_run IS NULL`` check), and the actor must be user-backed.

Production ingest does **not** funnel through here — it bulk-creates ChangeSets
directly in ``claim_ingest/apply/persist.py`` (a sanctioned bulk path). The
ingest branch below exists only so the test factories (``ingest_changeset`` /
``source_changeset``) can encode the same actor invariant through one seam. The
bulk path's actor guarantee comes from that module plus the AST persistence
guard and the cross-table invariant test, not from this funnel.

Sits at the ``validation`` tier of the provenance internal stack: it imports
only ``models.ChangeSet`` at runtime, so its importers — ``revert``, the
``claim_edit`` engine and the test factories — all reach it as a clean downward
edge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.provenance.models import ChangeSet

if TYPE_CHECKING:
    from apps.actors.models import Actor
    from apps.provenance.models import ChangeSetAction, IngestRun


def record_changeset(
    *,
    actor: Actor,
    action: ChangeSetAction | None = None,
    ingest_run: IngestRun | None = None,
    note: str = "",
) -> ChangeSet:
    """Create an attributed ChangeSet, always stamping ``actor``.

    Two shapes, discriminated by ``ingest_run``:

    * **interactive** (``ingest_run is None``): an ``action`` is required and the
      ``actor`` must be user-backed.
    * **ingest** (``ingest_run`` given): ``action`` must be ``None`` (ingest
      ChangeSets never carry one) and ``actor`` must be the run's source actor.

    ``actor`` is a required keyword arg; callers convert at the boundary
    (``user.actor`` / ``run.source.actor``) so this layer speaks ``actor`` only.
    """
    if ingest_run is None:
        if action is None:
            raise ValueError("An interactive ChangeSet requires an action.")
        # Reverse one-to-one: ``RelatedObjectDoesNotExist`` subclasses
        # AttributeError, so getattr returns None for a non-user actor.
        if getattr(actor, "user", None) is None:
            raise ValueError(
                "An interactive ChangeSet requires a user-backed actor; "
                f"got a {actor.backing_model!r} actor."
            )
        return ChangeSet.objects.create(actor=actor, action=action, note=note)

    if action is not None:
        raise ValueError("Ingest ChangeSets never carry an action.")
    if actor.pk != ingest_run.source.actor_id:
        raise ValueError("Ingest ChangeSet actor must be the run's source actor.")
    return ChangeSet.objects.create(actor=actor, ingest_run=ingest_run, note=note)
