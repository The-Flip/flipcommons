"""ModelRelationship: typed, claim-controlled edges between machine models.

The edge table behind copies, conversions and conversion kits — see
docs/plans/catalog_data_model/ModelRelationships.md. Each row relates a subject
MachineModel to a target at one of two resolutions: a seeded machine
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
    "RELATIONSHIP_CHIPS",
    "RELATIONSHIP_CHIPS_BY_SLUG",
    "LicenseStatus",
    "ModelRelationship",
    "RelationshipChip",
    "RelationshipType",
    "relationship_chip_exists",
]

TARGET_LABEL_MAX_LENGTH = 300


class RelationshipType(models.TextChoices):
    """How the subject model relates to its target.

    ``CONVERSION`` is a complete converted machine ("built from this donor");
    ``CONVERSION_KIT`` is a kit ("compatible with this donor"); ``COPY``
    reproduces the target's design on new hardware.
    """

    CONVERSION = "conversion", "Conversion"
    CONVERSION_KIT = "conversion_kit", "Conversion kit"
    COPY = "copy", "Copy"


class LicenseStatus(models.TextChoices):
    """Whether the relationship was authorized by the target's rights holder."""

    LICENSED = "licensed", "Licensed"
    UNLICENSED = "unlicensed", "Unlicensed"
    UNKNOWN = "unknown", "Unknown"


class ModelRelationship(ClaimThroughModel):
    """One typed edge from a MachineModel to a donor/original.

    The claim identity is the target alone (``target_machine`` XOR
    ``target_label``) — one edge per (model, target). ``relationship_type``
    and ``license_status`` are payload, so corrections supersede in place and
    disagreements contest one edge instead of forking two. ``target_label``
    uses the CharField convention: ``""`` means absent, never NULL.

    Existence is controlled by ``"model_relationship"`` relationship claims on
    MachineModel — do not create or delete rows directly.
    """

    claim_relationship_spec: ClassVar[ClaimRelationshipSpec] = ClaimRelationshipSpec(
        namespace="model_relationship",
        subject=SingleSubject("machine_model"),
        members=(
            MemberField("target_machine", identity="target_machine", nullable=True),
            MemberField("target_label", identity="target_label"),
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
            models.CheckConstraint(
                condition=models.Q(license_status__in=LicenseStatus.values),
                name="catalog_modelrelationship_license_status_valid",
            ),
            # One edge per (model, target): one conditional constraint per
            # target rung, because the nullable FK makes a single
            # unconditional constraint useless (NULLs compare distinct).
            models.UniqueConstraint(
                fields=["machine_model", "target_machine"],
                condition=models.Q(target_machine__isnull=False),
                name="catalog_modelrelationship_unique_machine_target",
            ),
            models.UniqueConstraint(
                fields=["machine_model", "target_label"],
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


class RelationshipChip(NamedTuple):
    """One derived filter chip over relationship edges.

    The bootleg / licensed-build / conversion-kit chips replace the retired
    tags of the same names ("an edge exists" + type + license_status); copy and
    conversion complete the set. ``license_status=None`` means any. Declared
    rather than derived because bootleg and licensed-build are domain names for
    (type, status) combinations the enums alone can't express.
    """

    slug: str
    label: str
    relationship_type: RelationshipType
    license_status: LicenseStatus | None = None


RELATIONSHIP_CHIPS: tuple[RelationshipChip, ...] = (
    RelationshipChip("copy", "Copy", RelationshipType.COPY),
    RelationshipChip(
        "bootleg", "Bootleg", RelationshipType.COPY, LicenseStatus.UNLICENSED
    ),
    RelationshipChip(
        "licensed-build",
        "Licensed build",
        RelationshipType.COPY,
        LicenseStatus.LICENSED,
    ),
    RelationshipChip("conversion", "Conversion", RelationshipType.CONVERSION),
    RelationshipChip(
        "conversion-kit", "Conversion kit", RelationshipType.CONVERSION_KIT
    ),
)

RELATIONSHIP_CHIPS_BY_SLUG: dict[str, RelationshipChip] = {
    chip.slug: chip for chip in RELATIONSHIP_CHIPS
}


def relationship_chip_exists(chip: RelationshipChip) -> models.Exists:
    """An ``Exists()`` over the chip's edges, correlated on the subject model pk.

    The chip query surface (docs/plans/catalog_data_model/ModelRelationships.md
    → Rework tags): a plain correlated subquery, no materialization — revisit
    only if the chip filters prove slow.
    """
    edges = ModelRelationship.objects.filter(
        machine_model=models.OuterRef("pk"),
        relationship_type=chip.relationship_type,
    )
    if chip.license_status is not None:
        edges = edges.filter(license_status=chip.license_status)
    return models.Exists(edges)
