"""Claim model: atomic fact assertions about catalog entities.

The mint primitive that writes ``Claim`` rows lives in
``apps.provenance.claim_writer`` (``_assert_claim``), not on a custom manager —
see that module and ``tests/test_single_claim_write_path.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models.functions import Now

from apps.actors.types import ActorId
from apps.core.models import BoundedTextField, field_not_blank
from apps.core.types import ClaimFieldName, ClaimKey, ContentTypeId, LicenseId

from ..model_bases import ClaimControlledModel
from ..types import ChangeSetId
from .changeset import ChangeSet

CLAIM_CITATION_MAX_LENGTH = 2_000

if TYPE_CHECKING:
    from .citation_instance import CitationInstance

type IdentityPartName = str
"""One key in a claim_key's identity-parts mapping — the label of an identity
slot (e.g. ``person``, ``role``, ``alias``). Distinct from the relationship
value-dict key it derives from: usually equal, occasionally not (``alias`` for
the ``alias_value`` slot)."""

type IdentityPartValue = str | int | None
"""One value in a claim_key's identity-parts mapping: an entity-reference PK
(``int``), a literal key like an alias value (``str``), or ``None``
(serialized as the literal ``"null"`` in the key)."""


class ExistingClaimRow(NamedTuple):
    """Partial Claim row cached during claim diffing.

    Fetched via ``values_list`` to avoid JSONField deserialization cost on
    large sources. Field order matches the ``values_list`` column order.
    """

    # ``value`` is the raw JSONField payload — scalar, dict, list, or null.
    value: object
    license_id: LicenseId | None
    pk: int


def _escape_claim_value(s: str) -> str:
    """Percent-escape reserved delimiters in claim key identity values."""
    return s.replace("%", "%25").replace("|", "%7C").replace(":", "%3A")


def make_claim_key(
    field_name: ClaimFieldName, **identity_parts: IdentityPartValue
) -> ClaimKey:
    """Build a canonical claim_key from field_name and sorted identity parts.

    For scalar claims, call with just field_name (returns field_name unchanged).
    For relationship claims, pass identity parts as keyword arguments.

    Reserved characters (``|`` and ``:``) in identity values are
    percent-escaped so the key remains unambiguous.
    """
    if not identity_parts:
        return field_name
    parts = [field_name]
    for k in sorted(identity_parts):
        v = identity_parts[k]
        s = "null" if v is None else str(v)
        parts.append(f"{k}:{_escape_claim_value(s)}")
    return "|".join(parts)


class Claim(models.Model):
    """A single fact asserted by an actor about any catalog entity.

    Uses a GenericForeignKey (``subject``) so claims can target any model:
    MachineModel, Manufacturer, Person, etc.

    Attribution is carried by ``actor`` (a denormalized copy of
    ``changeset.actor``) — set on every row by ``claim_writer._assert_claim``.
    """

    content_type_id: ContentTypeId
    actor_id: ActorId
    license_id: LicenseId | None
    changeset_id: ChangeSetId
    retracted_by_changeset_id: ChangeSetId | None
    citation_instances: models.Manager[CitationInstance]

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey("content_type", "object_id")

    # Denormalized copy of ``changeset.actor`` (the source of truth). Backs the
    # unified active-claim unique index and is the sole attribution column.
    actor = models.ForeignKey(
        "actors.Actor",
        on_delete=models.PROTECT,
        related_name="claims",
    )
    field_name = models.CharField(max_length=255)
    claim_key = models.CharField(
        max_length=255,
        help_text=(
            "Identity key for uniqueness. Equals field_name for scalar claims. "
            "For relationship claims, encodes the relationship identity "
            '(e.g., "credit|person:pat-lawlor|role:art").'
        ),
    )
    changeset = models.ForeignKey(
        ChangeSet,
        on_delete=models.PROTECT,
        related_name="claims",
        help_text="The edit session that wrote this claim; carries its attribution.",
    )
    retracted_by_changeset = models.ForeignKey(
        ChangeSet,
        on_delete=models.PROTECT,
        related_name="retracted_claims",
        null=True,
        blank=True,
        help_text="The changeset that deactivated this claim (user revert or full_sync retraction).",
    )
    value = models.JSONField()
    citation = BoundedTextField(
        max_length=CLAIM_CITATION_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
    )
    license = models.ForeignKey(
        "core.License",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="claims",
        help_text="Per-claim license override. Null inherits from source field license or source default.",
    )
    is_active = models.BooleanField(
        default=True,
        db_default=True,
        help_text="Current assertion from this author for this claim_key on this subject. False = superseded or retracted.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id", "field_name"]),
            models.Index(fields=["content_type", "object_id", "claim_key"]),
            models.Index(fields=["actor", "content_type", "object_id"]),
            models.Index(fields=["field_name", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "actor", "claim_key"],
                condition=models.Q(is_active=True),
                name="provenance_unique_active_claim_per_actor",
            ),
            field_not_blank("field_name"),
            field_not_blank("claim_key"),
            models.CheckConstraint(
                condition=(
                    models.Q(retracted_by_changeset__isnull=True)
                    | models.Q(is_active=False)
                ),
                name="provenance_claim_retracted_requires_inactive",
                violation_error_message=(
                    "retracted_by_changeset is only allowed when is_active=False."
                ),
                violation_error_code="cross_field",
            ),
        ]

    def __str__(self) -> str:
        try:
            author = str(getattr(self.actor, self.actor.backing_model))
        except ObjectDoesNotExist:  # orphaned actor (backing row deleted)
            author = f"[deleted {self.actor.backing_model}]"
        return f"{author}: {self.subject}.{self.field_name}"

    @classmethod
    def for_object(
        cls,
        obj: ClaimControlledModel,
        *,
        field_name: ClaimFieldName,
        value: object,
        claim_key: ClaimKey = "",
        **kwargs: object,
    ) -> Claim:
        """Construct an unsaved Claim for a model instance.

        Derives content_type_id from obj automatically, so callers never need
        to capture a ct_id variable. Returns an unsaved instance suitable for
        batch validation (``validate_claims_batch``).
        """
        ct_id = ContentType.objects.get_for_model(obj).pk
        return cls(
            content_type_id=ct_id,
            object_id=obj.pk,
            field_name=field_name,
            claim_key=claim_key,
            value=value,
            **kwargs,
        )
