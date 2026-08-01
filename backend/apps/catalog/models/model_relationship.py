"""ModelRelationship: typed, claim-controlled edges between machine models.

The edge table behind copies, conversions and conversion kits. Each row relates a
subject MachineModel to a target at one of two resolutions: a seeded machine
(``target_machine``) or a free-text descriptor (``target_label``, e.g.
"several Gottlieb EM models") when the donor isn't seeded. Licensing status is
an orthogonal payload axis, so "bootleg" is ``(copy, unlicensed)`` rather than
its own relationship kind.
"""

from __future__ import annotations

from typing import ClassVar, NamedTuple

from django.db import models

from apps.core.validators import validate_no_mojibake
from apps.provenance.model_bases import (
    ClaimRelationshipSpec,
    ClaimThroughModel,
    MemberField,
    MemberXor,
    PayloadField,
    SingleSubject,
)

__all__ = [
    "MACHINE_TARGET_REQUIRED_TYPES",
    "RELATIONSHIP_TYPE_BEHAVIOR",
    "SUBORDINATING_RELATIONSHIP_TYPES",
    "LicenseStatus",
    "ModelRelationship",
    "RelationshipType",
    "RelationshipTypeBehavior",
]

TARGET_LABEL_MAX_LENGTH = 300


class RelationshipType(models.TextChoices):
    """How the subject model relates to its target.

    ``CONVERSION`` is a complete converted machine ("built from this donor");
    ``CONVERSION_KIT`` is a kit ("compatible with this donor"); ``COPY``
    reproduces the target's design on new hardware; ``RETHEME`` keeps a donor's
    gameplay and re-skins it with new art and theme.
    """

    CONVERSION = "conversion", "Conversion"
    CONVERSION_KIT = "conversion_kit", "Conversion kit"
    COPY = "copy", "Copy"
    RETHEME = "retheme", "Re-theme"


class LicenseStatus(models.TextChoices):
    """Whether the relationship was authorized by the target's rights holder."""

    LICENSED = "licensed", "Licensed"
    UNLICENSED = "unlicensed", "Unlicensed"
    UNKNOWN = "unknown", "Unknown"


class RelationshipTypeBehavior(NamedTuple):
    """The catalog-semantics decisions every relationship type must make."""

    subordinates: bool
    """Does an edge of this type demote its subject below the original when
    picking a Title's representative model? The Big Ben rule — a copy never
    heads its Title, so a subordinating subject sorts after every original in
    :meth:`MachineModel.first_model_candidates`. (A Title whose *only* model is
    a copy still surfaces it; subordination is a tiebreak against originals, not
    a bar on ever being representative.)"""

    requires_machine_target: bool
    """Must an edge of this type resolve to a seeded ``target_machine``, never a
    free-text ``target_label``? True where the donor is always known and seeded,
    so a label rung would be a data error rather than a lower resolution (a
    re-theme names its donor in every IPDB note). Derives
    ``MACHINE_TARGET_REQUIRED_TYPES``, which drives both the DB CHECK below and
    the planner's row-level rejection."""


RELATIONSHIP_TYPE_BEHAVIOR: dict[RelationshipType, RelationshipTypeBehavior] = {
    RelationshipType.CONVERSION: RelationshipTypeBehavior(
        subordinates=False, requires_machine_target=False
    ),
    RelationshipType.CONVERSION_KIT: RelationshipTypeBehavior(
        subordinates=False, requires_machine_target=False
    ),
    RelationshipType.COPY: RelationshipTypeBehavior(
        subordinates=True, requires_machine_target=False
    ),
    # A re-theme usually gets its own Title, but not always — Metallica
    # (Retheme) sits under the Earthshaker Title alongside its donor — and where
    # it does, the original heads the Title, never the re-skin (the Big Ben
    # rule). Don't lean on the year tiebreak to get this right: a donor is
    # necessarily older, but an undated re-theme would sort ahead of it. Its
    # donor is always known and seeded (IPDB names it in every note), so a
    # free-text label rung would be a data error: require a machine target.
    RelationshipType.RETHEME: RelationshipTypeBehavior(
        subordinates=True, requires_machine_target=True
    ),
}
"""Per-type behavior classification — the forcing function for new types.

Consumers derive their type sets from this table instead of naming values
inline (``SUBORDINATING_RELATIONSHIP_TYPES`` for representative-model selection,
``MACHINE_TARGET_REQUIRED_TYPES`` for the target CHECK and planner). An
exhaustiveness test fails on any ``RelationshipType`` value missing here, and the
``RelationshipTypeBehavior`` constructor requires every field, so adding a type
(e.g. ``retheme``) goes red until it explicitly decides each behavior, rather
than silently inheriting a default.
"""

SUBORDINATING_RELATIONSHIP_TYPES: tuple[RelationshipType, ...] = tuple(
    t for t, behavior in RELATIONSHIP_TYPE_BEHAVIOR.items() if behavior.subordinates
)

MACHINE_TARGET_REQUIRED_TYPES: tuple[RelationshipType, ...] = tuple(
    t
    for t, behavior in RELATIONSHIP_TYPE_BEHAVIOR.items()
    if behavior.requires_machine_target
)


class ModelRelationship(ClaimThroughModel):
    """One typed edge from a MachineModel to a donor/original.

    The claim identity is ``target_machine`` alone (nullable): one edge per
    (model, machine target), plus at most **one** label edge per model — the
    label's identity is its slot, not its wording, so ``target_label`` is a
    non-identity member and a reword supersedes the edge in place (same row,
    citations intact) instead of forking a second edge. ``relationship_type``
    and ``license_status`` are payload, so corrections likewise supersede in
    place and disagreements contest one edge. ``target_label`` uses the
    CharField convention: ``""`` means absent, never NULL.

    Existence is controlled by ``"model_relationship"`` relationship claims on
    MachineModel — do not create or delete rows directly.
    """

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="model_relationship",
        subject=SingleSubject("machine_model"),
        members=(
            MemberField("target_machine", identity="target_machine", nullable=True),
            # Non-identity member: authorable, materialized and displayed as
            # the target, but outside the claim_key — the label slot is the
            # identity, not the wording.
            MemberField("target_label"),
        ),
        payload=(
            PayloadField("relationship_type", required=True),
            PayloadField("license_status", required=True),
        ),
        member_xor=MemberXor(groups=(("target_machine",), ("target_label",))),
    )

    machine_model_id: int
    target_machine_id: int | None

    machine_model = models.ForeignKey(
        "catalog.MachineModel",
        on_delete=models.CASCADE,
        related_name="relationships",
        help_text="The subject model this edge belongs to.",
    )
    target_machine = models.ForeignKey(
        "catalog.MachineModel",
        on_delete=models.PROTECT,
        related_name="inbound_relationships",
        null=True,
        blank=True,
        help_text="The fully-resolved target/donor, when known and seeded.",
    )
    target_label = models.CharField(
        max_length=TARGET_LABEL_MAX_LENGTH,
        blank=True,
        default="",
        validators=[validate_no_mojibake],
        help_text=(
            "Free-text target descriptor when the donor isn't seeded "
            '("an unknown 1960s replay game"). Empty when target_machine is set.'
        ),
    )
    relationship_type = models.CharField(
        max_length=20,
        choices=RelationshipType.choices,
        help_text="How the subject relates to the target.",
    )
    license_status = models.CharField(
        max_length=20,
        choices=LicenseStatus.choices,
        default=LicenseStatus.UNKNOWN,
        help_text="Whether the relationship was authorized by the rights holder.",
    )

    class Meta:
        verbose_name = "model relationship"
        verbose_name_plural = "model relationships"
        constraints = [
            # The target XOR: a seeded machine or a label, exactly one.
            # Mirrors the spec's MemberXor (behavior-tested, per the credit
            # subject-XOR delegation).
            models.CheckConstraint(
                condition=(
                    models.Q(target_machine__isnull=False, target_label="")
                    | models.Q(target_machine__isnull=True) & ~models.Q(target_label="")
                ),
                name="catalog_modelrelationship_target_xor",
                violation_error_message=(
                    "Set either target_machine or target_label — "
                    "never both, never neither."
                ),
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(target_machine__isnull=True)
                | ~models.Q(target_machine=models.F("machine_model")),
                name="catalog_modelrelationship_target_not_self",
                violation_error_message=(
                    "A machine model cannot have a relationship to itself."
                ),
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(relationship_type__in=RelationshipType.values),
                name="catalog_modelrelationship_type_valid",
            ),
            # Derived from RELATIONSHIP_TYPE_BEHAVIOR: a type flagged
            # requires_machine_target may not use a label rung. Absent from the
            # DDL entirely until some type sets the flag, so no vacuous
            # empty-IN constraint ships (and it appears automatically when one
            # does).
            *(
                [
                    models.CheckConstraint(
                        condition=~models.Q(
                            relationship_type__in=MACHINE_TARGET_REQUIRED_TYPES
                        )
                        | models.Q(target_machine__isnull=False),
                        name="catalog_modelrelationship_machine_target_required",
                        violation_error_message=(
                            "This relationship type requires a seeded target "
                            "machine, not a text label."
                        ),
                        violation_error_code="cross_field",
                    )
                ]
                if MACHINE_TARGET_REQUIRED_TYPES
                else []
            ),
            models.CheckConstraint(
                condition=models.Q(license_status__in=LicenseStatus.values),
                name="catalog_modelrelationship_license_status_valid",
            ),
            # One edge per (model, machine target) plus one label edge per
            # model: one conditional constraint per target rung, because the
            # nullable FK makes a single unconditional constraint useless
            # (NULLs compare distinct). The label rung is keyed by the slot
            # alone — the wording is data, not identity — so two label edges
            # with different wordings still collide.
            models.UniqueConstraint(
                fields=["machine_model", "target_machine"],
                condition=models.Q(target_machine__isnull=False),
                name="catalog_modelrelationship_unique_machine_target",
            ),
            models.UniqueConstraint(
                fields=["machine_model"],
                condition=models.Q(target_machine__isnull=True),
                name="catalog_modelrelationship_unique_label_target",
            ),
        ]
        indexes = [
            models.Index(fields=["relationship_type", "license_status"]),
        ]

    def __str__(self) -> str:
        target = (
            str(self.target_machine)
            if self.target_machine_id is not None
            else self.target_label
        )
        return f"{self.machine_model} —{self.relationship_type}→ {target}"
