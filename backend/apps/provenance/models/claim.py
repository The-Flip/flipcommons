"""Claim model: atomic fact assertions about catalog entities.

The mint primitive that writes ``Claim`` rows lives in
``apps.provenance.claim_writer`` (``_assert_claim``), not on a custom manager —
see that module and ``tests/test_single_claim_write_path.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.functions import Now

from apps.core.models import BoundedTextField, field_not_blank

from ..model_bases import ClaimControlledModel
from .changeset import ChangeSet
from .source import Source

CLAIM_CITATION_MAX_LENGTH = 2_000
CLAIM_NEEDS_REVIEW_NOTES_MAX_LENGTH = 2_000

if TYPE_CHECKING:
    from .citation_instance import CitationInstance

type IdentityPart = str | int | None
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
    license_id: int | None
    pk: int


def _escape_claim_value(s: str) -> str:
    """Percent-escape reserved delimiters in claim key identity values."""
    return s.replace("%", "%25").replace("|", "%7C").replace(":", "%3A")


def make_claim_key(field_name: str, **identity_parts: IdentityPart) -> str:
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
    """A single fact asserted by a Source or User about any catalog entity.

    Uses a GenericForeignKey (``subject``) so claims can target any model:
    MachineModel, Manufacturer, Person, etc.

    Exactly one of ``source`` or ``user`` must be set — enforced by a
    CheckConstraint and by ``claim_writer._assert_claim``.
    """

    content_type_id: int
    source_id: int | None
    user_id: int | None
    actor_id: int
    license_id: int | None
    changeset_id: int
    retracted_by_changeset_id: int | None
    citation_instances: models.Manager[CitationInstance]

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey("content_type", "object_id")

    source = models.ForeignKey(
        Source,
        on_delete=models.PROTECT,
        related_name="claims",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="claims",
        null=True,
        blank=True,
    )
    # Denormalized copy of ``changeset.actor`` (the source of truth). Backs the
    # unified active-claim unique index and replaces the legacy source/user pair,
    # which survives only until "Drop dead stuff".
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
    needs_review = models.BooleanField(
        default=False,
        db_default=False,
        help_text="Flag for low-confidence claims that need human review.",
    )
    needs_review_notes = BoundedTextField(
        max_length=CLAIM_NEEDS_REVIEW_NOTES_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
        help_text="Context for reviewers about why this claim needs attention.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id", "field_name"]),
            models.Index(fields=["content_type", "object_id", "claim_key"]),
            models.Index(fields=["source", "content_type", "object_id"]),
            models.Index(fields=["user", "content_type", "object_id"]),
            models.Index(fields=["actor", "content_type", "object_id"]),
            models.Index(fields=["field_name", "is_active"]),
            models.Index(fields=["source", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(source__isnull=False, user__isnull=True)
                    | models.Q(source__isnull=True, user__isnull=False)
                ),
                name="provenance_claim_source_xor_user",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id", "source", "claim_key"],
                condition=models.Q(is_active=True, source__isnull=False),
                name="provenance_unique_active_claim_per_source",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id", "user", "claim_key"],
                condition=models.Q(is_active=True, user__isnull=False),
                name="provenance_unique_active_claim_per_user",
            ),
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
        if self.source is not None:
            author = self.source.name
        else:
            author = self.user.username if self.user is not None else "unknown"
        return f"{author}: {self.subject}.{self.field_name}"

    @classmethod
    def for_object(
        cls,
        obj: ClaimControlledModel,
        *,
        field_name: str,
        value: object,
        claim_key: str = "",
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
