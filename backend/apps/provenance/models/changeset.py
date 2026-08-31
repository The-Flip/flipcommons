"""ChangeSet model: grouped edit sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models.functions import Now

from apps.actors.types import ActorId
from apps.core.models import BoundedTextField

from ..types import IngestRunId

if TYPE_CHECKING:
    from .claim import Claim


CHANGESET_NOTE_MAX_LENGTH = 1_000


class ChangeSetAction(models.TextChoices):
    CREATE = "create", "Create"
    EDIT = "edit", "Edit"
    DELETE = "delete", "Delete"
    REVERT = "revert", "Revert"


class ChangeSet(models.Model):
    """A grouped edit session that links related claims.

    A ChangeSet is a thin grouping record, not a snapshot of entity state.
    Truth is always derived from claim resolution (highest priority wins).
    Reverting a claim means deactivating it and re-resolving — the
    resolution machinery picks the correct winner from whatever remains.

    All claims in a ChangeSet share the same ``actor``. ``ingest_run``
    discriminates batch (ingest) from interactive edits — interactive
    ChangeSets carry an ``action`` and a user-backed actor, ingest ones
    don't; both invariants are enforced by ``changeset_writer.record_changeset``.
    """

    claims: models.Manager[Claim]
    retracted_claims: models.Manager[Claim]
    ingest_run_id: IngestRunId | None
    actor_id: ActorId

    ingest_run = models.ForeignKey(
        "provenance.IngestRun",
        on_delete=models.PROTECT,
        related_name="changesets",
        null=True,
        blank=True,
        help_text="The ingest run that produced this changeset. Null for user edits.",
    )
    action = models.CharField(
        max_length=8,
        choices=ChangeSetAction.choices,
        null=True,
        blank=True,
        help_text=(
            "What kind of user-driven action this ChangeSet represents. "
            "Populated for every user ChangeSet; always NULL for ingest."
        ),
    )
    # The single attribution target. Every reader resolves attribution through
    # this; ``ingest_run`` remains only as batch metadata, not attribution.
    actor = models.ForeignKey(
        "actors.Actor",
        on_delete=models.PROTECT,
        related_name="changesets",
        help_text="The actor this changeset is attributed to.",
    )
    note = BoundedTextField(
        max_length=CHANGESET_NOTE_MAX_LENGTH,
        blank=True,
        default="",
        help_text="Optional free-text note explaining the edit.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # The key ``cursor_paginate`` walks the changes feed on. Without
            # it the feed sorts every changeset per request, and the
            # entity-type filter has no ordered stream to stop early against,
            # so it materializes changeset x claim and sorts that to disk.
            models.Index(
                fields=["-created_at", "-id"],
                name="provenance_cs_created_id",
            ),
            models.Index(
                fields=["actor", "-created_at"],
                name="provenance_cs_actor_created",
            ),
            models.Index(
                fields=["actor", "action", "-created_at"],
                name="provenance_cs_actor_action",
            ),
        ]
        constraints = [
            # Action is present exactly for interactive edits (no ingest_run)
            # and always absent for ingest batches.
            models.CheckConstraint(
                condition=(
                    models.Q(ingest_run__isnull=True, action__isnull=False)
                    | models.Q(ingest_run__isnull=False, action__isnull=True)
                ),
                name="provenance_changeset_action_iff_interactive",
            ),
        ]

    def __str__(self) -> str:
        try:
            label = str(getattr(self.actor, self.actor.backing_model))
        except ObjectDoesNotExist:  # orphaned actor (backing row deleted)
            label = f"[deleted {self.actor.backing_model}]"
        return f"ChangeSet #{self.pk} by {label}"
