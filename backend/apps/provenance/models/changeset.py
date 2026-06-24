"""ChangeSet model: grouped edit sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.db.models.functions import Now

from apps.core.models import BoundedTextField

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

    All claims in a ChangeSet must share the same actor (same user or same
    source). A CheckConstraint enforces that exactly one of user or
    ingest_run is set; same-actor consistency within those groups is
    enforced by assert_claim().
    """

    claims: models.Manager[Claim]
    retracted_claims: models.Manager[Claim]
    user_id: int | None
    ingest_run_id: int | None
    actor_id: int | None

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="changesets",
        null=True,
        blank=True,
        help_text="The user who made this edit. Null for source-level changesets.",
    )
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
    # Single attribution target. Nullable for now; a later PR ("Backfill actor
    # FKs") populates it from user / ingest_run.source, then it supersedes the
    # user-XOR-ingest_run fork. Nothing reads it yet.
    actor = models.ForeignKey(
        "actors.Actor",
        on_delete=models.PROTECT,
        related_name="changesets",
        null=True,
        blank=True,
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
            models.Index(
                fields=["user", "-created_at"],
                name="provenance_cs_user_created",
            ),
            models.Index(
                fields=["user", "action", "-created_at"],
                name="provenance_cs_user_action",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, ingest_run__isnull=True)
                    | models.Q(user__isnull=True, ingest_run__isnull=False)
                ),
                name="provenance_changeset_user_xor_ingest_run",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, action__isnull=False)
                    | models.Q(user__isnull=True, action__isnull=True)
                ),
                name="provenance_changeset_action_iff_user",
            ),
        ]

    def __str__(self) -> str:
        if self.user is not None:
            actor = self.user.username
        else:
            ingest_run = self.ingest_run
            actor = (
                f"ingest:{ingest_run.source.name}"
                if ingest_run is not None
                else "ingest:unknown"
            )
        return f"ChangeSet #{self.pk} by {actor}"
