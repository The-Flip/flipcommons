"""IngestRun model: run-level audit trail for source ingestion."""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Lower, Now

from .source import Source


class IngestRun(models.Model):
    """A single invocation of an ingest pipeline for one source.

    Created before the apply transaction begins (status='running') and
    finalised after it commits or rolls back.  If the transaction fails,
    the IngestRun survives with status='failed' and error details — which
    is exactly when the audit record matters most.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(
        Source,
        on_delete=models.PROTECT,
        related_name="ingest_runs",
    )
    started_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)
    input_fingerprint = models.CharField(
        max_length=255,
        help_text="Hash of the source data file.",
    )
    patch_id = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Identity of a data patch (the NNNN-slug filename stem). "
            "Null for normal ingests; set for patch applications. The "
            "applied-ledger keys on this: a success run with a patch_id "
            "means that patch has been applied to this database."
        ),
    )
    note = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Free-text note about the run. For patch runs, holds the "
            "patch's description."
        ),
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        db_default=Status.RUNNING,
        help_text=(
            "running — set at creation; a stale running record with an old "
            "timestamp indicates a crash. "
            "success — transaction committed, all data persisted. "
            "failed — exception caught, transaction rolled back."
        ),
    )

    # ── Run statistics ──────────────────────────────────────────────
    records_parsed = models.PositiveIntegerField(db_default=0)
    records_matched = models.PositiveIntegerField(db_default=0)
    records_created = models.PositiveIntegerField(db_default=0)
    claims_asserted = models.PositiveIntegerField(db_default=0)
    claims_retracted = models.PositiveIntegerField(db_default=0)
    claims_rejected = models.PositiveIntegerField(db_default=0)

    warnings = models.JSONField(
        default=list,
        blank=True,
    )
    errors = models.JSONField(
        default=list,
        blank=True,
    )

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["running", "success", "failed"]),
                name="provenance_ingestrun_status_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(input_fingerprint=""),
                name="provenance_ingestrun_fingerprint_nonempty",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="running", finished_at__isnull=True)
                    | (
                        ~models.Q(status="running")
                        & models.Q(finished_at__isnull=False)
                    )
                ),
                name="provenance_ingestrun_finished_iff_not_running",
                violation_error_message=(
                    "running requires finished_at=NULL; "
                    "success/failed requires finished_at to be set."
                ),
                violation_error_code="cross_field",
            ),
            # patch_id is a non-empty lowercase identifier. The exact
            # NNNN-slug *format* is enforced in the clean path (ingest_patches'
            # pre-flight); the DB check stays portable. Regex CHECKs are
            # avoided repo-wide — they compile to REGEXP, which fails or
            # silently no-ops on a SQLite DB opened outside Django (issue
            # #357; see test_lowercase_constraint). Defense-in-depth behind
            # the command, catching direct writes that bypass it.
            models.CheckConstraint(
                condition=(
                    models.Q(patch_id__isnull=True)
                    | (~models.Q(patch_id="") & models.Q(patch_id=Lower("patch_id")))
                ),
                name="provenance_ingestrun_patch_id_lowercase",
                violation_error_message=(
                    "patch_id must be a non-empty lowercase string."
                ),
            ),
            # At most one successful application per patch. Multiple
            # running/failed attempts and unlimited null-patch_id ingests
            # remain allowed. This is the DB-level "applied once" invariant.
            models.UniqueConstraint(
                fields=["patch_id"],
                condition=models.Q(status="success"),
                name="provenance_ingestrun_patch_applied_once",
            ),
        ]

    def __str__(self) -> str:
        return f"IngestRun #{self.pk} ({self.source.name}, {self.status})"
