"""ModelExportMarket: claim-controlled export-market rows on machine models.

The join table behind "built for export to [market]". Each row records one export
destination for a subject MachineModel at one of three resolutions: a seeded
country (``target_market_location``), a free-text region label
(``target_market_label``, e.g. "Europe") when the market is not a single
country, or neither — the bottom rung, where the row's existence records
"built for export" with an unknown destination.

A model's rows take exactly one of three shapes: multiple
country rows, a single label row, or a single unknown row. The DB enforces
the per-shape uniqueness below; the "a null-location row must be the model's
only row" mix rule is a write-path invariant (the editor planner enforces it —
SQLite can't express the cross-row CHECK), not a hard DB constraint.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.validators import validate_no_mojibake
from apps.provenance.model_bases import (
    ClaimRelationshipSpec,
    ClaimThroughModel,
    MemberField,
    MemberXor,
    SingleSubject,
    TargetFilter,
)

__all__ = [
    "COUNTRY_TARGET_FILTER",
    "TARGET_MARKET_LABEL_MAX_LENGTH",
    "ModelExportMarket",
]

TARGET_MARKET_LABEL_MAX_LENGTH = 120

# Only top-level Locations (countries) are legal market targets; a region
# that isn't a country ("Europe") is a label, and a narrower place (a city,
# a subdivision) is a data error. Declared once here and consumed by every
# target-validity decision — resolution's valid-PK set, the batch claim
# validator, the patch adapter and the editor planner.
COUNTRY_TARGET_FILTER = TargetFilter(
    lookups=(("parent__isnull", True),),
    description="a country (top-level location)",
)


class ModelExportMarket(ClaimThroughModel):
    """One export-market row on a MachineModel.

    The claim identity is ``target_market_location`` alone (nullable): one row
    per (model, country), plus at most **one** null-location row per model —
    the null-location row's identity is its slot, so ``target_market_label``
    is a non-identity member and rewording a region label supersedes the row
    in place (same row, citations intact). ``target_market_label`` uses the
    CharField convention: ``""`` means absent, never NULL. A row with both
    target fields absent is the legal unknown-market shape — the row itself
    asserts "built for export".

    Existence is controlled by ``"export_market"`` relationship claims on
    MachineModel — do not create or delete rows directly.
    """

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="export_market",
        subject=SingleSubject("machine_model"),
        members=(
            MemberField(
                "target_market_location",
                identity="target_market_location",
                nullable=True,
                target_filter=COUNTRY_TARGET_FILTER,
            ),
            # Non-identity member: authorable, materialized and displayed as
            # the market, but outside the claim_key — the null-location slot
            # is the identity, not the label wording.
            MemberField("target_market_label"),
        ),
        # At most one target rung — the all-absent row is the legal
        # unknown-market shape, so this is an optional XOR, not a strict one.
        member_xor=MemberXor(
            groups=(("target_market_location",), ("target_market_label",)),
            required=False,
        ),
    )

    machine_model_id: int
    target_market_location_id: int | None

    machine_model = models.ForeignKey(
        "catalog.MachineModel",
        on_delete=models.CASCADE,
        related_name="export_markets",
        help_text="The subject model this export-market row belongs to.",
    )
    target_market_location = models.ForeignKey(
        "catalog.Location",
        on_delete=models.PROTECT,
        related_name="export_markets",
        null=True,
        blank=True,
        help_text=(
            "The destination country, when known and seeded. "
            "Must be a top-level Location (a country)."
        ),
    )
    target_market_label = models.CharField(
        max_length=TARGET_MARKET_LABEL_MAX_LENGTH,
        blank=True,
        default="",
        validators=[validate_no_mojibake],
        help_text=(
            'Free-text market descriptor when the market is not a country ("Europe"). '
            "Empty when target_market_location is set, and empty on the "
            "unknown-market row."
        ),
    )

    class Meta:
        verbose_name = "model export market"
        verbose_name_plural = "model export markets"
        constraints = [
            # The target ladder: a country, a label, or neither — never both.
            # Mirrors the spec's optional MemberXor (behavior-tested, per the
            # credit subject-XOR delegation).
            models.CheckConstraint(
                condition=models.Q(target_market_location__isnull=True)
                | models.Q(target_market_label=""),
                name="catalog_modelexportmarket_target_at_most_one",
                violation_error_message=(
                    "Set a target country or a market label — never both."
                ),
                violation_error_code="cross_field",
            ),
            # One row per (model, country) plus one null-location row per
            # model: one conditional constraint per rung, because the nullable
            # FK makes a single unconditional constraint useless (NULLs
            # compare distinct). The null-location rung is keyed by the slot
            # alone — the label wording is data, not identity.
            models.UniqueConstraint(
                fields=["machine_model", "target_market_location"],
                condition=models.Q(target_market_location__isnull=False),
                name="catalog_modelexportmarket_unique_location_target",
            ),
            models.UniqueConstraint(
                fields=["machine_model"],
                condition=models.Q(target_market_location__isnull=True),
                name="catalog_modelexportmarket_unique_null_location",
            ),
        ]

    def __str__(self) -> str:
        if self.target_market_location_id is not None:
            market = str(self.target_market_location)
        else:
            market = self.target_market_label or "(unknown market)"
        return f"{self.machine_model} —export→ {market}"
