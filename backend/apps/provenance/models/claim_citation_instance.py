"""ClaimCitationInstance: the support edge linking a Claim to shared evidence."""

from __future__ import annotations

from django.db import models

from apps.core.types import CitationInstanceId

from ..types import ClaimId


class ClaimCitationInstance(models.Model):
    """The support edge for scalar/edit citations: one row per (claim, instance).

    A claim reaches 0..N citation instances and an instance is reached by 0..N
    claims through this join. Inline [[cite:slug]] footnotes do NOT use the join
    -- they stay marker-native and reach the shared instance through their
    marker -- so this table carries scalar/edit cites only. No changeset FK and
    no created_at -- both derive through ``claim`` (the link is born in the same
    write as its immutable claim), so storing them here would be a second source
    of truth.
    """

    claim_id: ClaimId
    citation_instance_id: CitationInstanceId

    claim = models.ForeignKey(
        "provenance.Claim",
        on_delete=models.CASCADE,
        related_name="citation_links",
    )
    citation_instance = models.ForeignKey(
        "provenance.CitationInstance",
        on_delete=models.PROTECT,
        related_name="claim_links",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["claim", "citation_instance"],
                name="prov_claimcite_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"Claim {self.claim_id} -> CitationInstance {self.citation_instance_id}"
