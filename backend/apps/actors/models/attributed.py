"""Editorial attribution for directly-edited, non-claims-controlled models."""

from __future__ import annotations

from django.db import models


class ActorAttributedModel(models.Model):
    """Abstract base adding editorial attribution: who created / last updated.

    Two nullable FKs to :class:`~apps.actors.models.actor.Actor`
    (``created_by`` / ``updated_by``), both ``PROTECT`` so the durable
    attribution anchor outlives the rows that reference it, and
    ``related_name="+"`` because no reverse "things this actor authored"
    accessor is wanted. ``null`` because a row may be authored by no one — an
    extractor-minted source can stay unattributed.

    This is *editorial* attribution for directly-edited, non-claims-controlled
    models (the citation-source family). It is **not** the claims/provenance
    system — claim-controlled catalog fields record authorship through
    ``ChangeSet``/``Claim``, which point at the same ``Actor``. Routing
    editorial attribution through ``Actor`` too means an ingest ``Source`` (a
    data patch) attributes the rows it creates exactly as a user does, via
    ``user.actor`` / ``source.actor``.

    Callers set the fields explicitly (admin ``save_model``/``save_formset``,
    the interactive API create paths, the patch ``sources:`` upsert); the base
    only declares the columns so the two FK blocks aren't copy-pasted per model.
    """

    created_by = models.ForeignKey(
        "actors.Actor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        "actors.Actor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True
