"""The Actor table: the single attribution/resolution target for every write.

``Actor`` is what every attributed write points at (``ChangeSet.actor`` /
``Claim.actor``) and the join key for all contribution/history queries. It is
NOT an identity, profile, auth, or credential record — those live on the
backing satellite (``User`` / ``Source`` / future bots), which point *down* at
their ``Actor`` via :class:`apps.actors.models.base.ActorModel`.
"""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Now

from apps.core.models import field_not_blank


class ActorResolutionStatus(models.TextChoices):
    """How claim resolution treats an actor's claims.

    Orthogonal to any auth/access state ("can't log in") — that lives on the
    User satellite, never here.
    """

    ACTIVE = "active", "Active"
    SUPPRESSED = "suppressed", "Suppressed"  # retained, but never win resolution


class Actor(models.Model):
    """Resolution/attribution record shared by all actor types.

    Created and linked only through ``ActorModel`` (the mint-on-save path on the
    backing record); never constructed directly. Carries no semantic kind enum —
    the only discriminator is the structural ``backing_model``, and type-specific
    behavior (``is_machine``, display routing) derives from the ActorModel
    registry, not from a column here.
    """

    # Reverse one-to-ones contributed by ActorModel subclasses via
    # related_name="%(class)s": ``actor.user`` (accounts.User),
    # ``actor.source`` (provenance.Source). Used by select_related on the
    # attribution read path. Each is present for exactly one backing type.

    backing_model = models.CharField(
        max_length=50,
        help_text="_meta.model_name of the backing record: 'user', 'source', …. "
        "Doubles as the select_related accessor and the registry key.",
    )
    priority = models.PositiveSmallIntegerField(
        help_text="Trust weight feeding claim resolution; higher wins. "
        "Mirrored from the backing record.",
    )
    resolution_status = models.CharField(
        max_length=10,
        choices=ActorResolutionStatus.choices,
        default=ActorResolutionStatus.ACTIVE,
        help_text="active = claims compete in resolution; "
        "suppressed = retained but never win.",
    )
    # When this attribution identity first existed. Lives on the anchor (not the
    # backing record) so it survives the backing record's deletion — the
    # backing record's own creation timestamp dies with it.
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            field_not_blank("backing_model"),
            models.CheckConstraint(
                condition=models.Q(
                    resolution_status__in=["active", "suppressed"],
                ),
                name="actors_actor_resolution_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"Actor #{self.pk} ({self.backing_model}, priority={self.priority})"
