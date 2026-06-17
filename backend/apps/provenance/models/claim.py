"""Claim model and manager: atomic fact assertions about catalog entities."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, NamedTuple

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models.functions import Now

from apps.core.models import BoundedTextField, field_not_blank

from .base import ClaimControlledModel
from .changeset import ChangeSet
from .source import Source

CLAIM_CITATION_MAX_LENGTH = 2_000
CLAIM_NEEDS_REVIEW_NOTES_MAX_LENGTH = 2_000

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.core.models import License

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
    citation: str
    needs_review: bool
    needs_review_notes: str
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


class ClaimManager(models.Manager["Claim"]):
    def assert_claim(
        self,
        subject: ClaimControlledModel,
        field_name: str,
        value: object,
        citation: str = "",
        *,
        source: Source | None = None,
        user: User | None = None,
        claim_key: str = "",
        license: License | None = None,
        changeset: ChangeSet | None = None,
    ) -> Claim:
        """Create a claim, deactivating any existing active claim for the same claim_key+author.

        ``subject`` can be any model instance (MachineModel, Manufacturer, Person, …).
        Exactly one of ``source`` or ``user`` must be provided.
        ``claim_key`` defaults to ``field_name`` for scalar claims.
        ``license`` is an optional per-claim License override (null inherits from source).
        ``changeset`` is an optional ChangeSet to group this claim with others.
        Runs in a transaction to ensure the old claim is deactivated atomically.
        """
        if (source is None) == (user is None):
            raise ValueError("Exactly one of source or user must be provided.")
        if changeset is not None:
            if (
                user is not None
                and changeset.user is not None
                and changeset.user.pk != user.pk
            ):
                raise ValueError("ChangeSet user must match the claim user.")
            ingest_run = changeset.ingest_run
            if source is not None and (
                ingest_run is None or ingest_run.source.pk != source.pk
            ):
                raise ValueError(
                    "ChangeSet must belong to an IngestRun from the same source."
                )
        if not claim_key:
            claim_key = field_name

        # Classify and validate. DIRECT claims get scalar/FK validation.
        # RELATIONSHIP claims get shape validation. EXTRA claims pass through.
        # UNRECOGNIZED claims are rejected outright.
        from apps.provenance.validation import (
            DIRECT,
            RELATIONSHIP,
            UNRECOGNIZED,
            classify_claim,
            validate_claim_value,
            validate_single_relationship_claim,
        )

        model_class = type(subject)
        ct_result = classify_claim(model_class, field_name, claim_key, value)
        if ct_result == UNRECOGNIZED:
            raise ValueError(
                f"Unrecognized claim field_name {field_name!r} on {model_class.__name__}"
            )
        if ct_result == DIRECT:
            value = validate_claim_value(field_name, value, model_class)
        elif ct_result == RELATIONSHIP:
            validate_single_relationship_claim(
                subject_model=model_class,
                field_name=field_name,
                claim_key=claim_key,
                value=value,
            )

        ct = ContentType.objects.get_for_model(subject)
        with transaction.atomic():
            self.filter(
                content_type=ct,
                object_id=subject.pk,
                source=source,
                user=user,
                claim_key=claim_key,
                is_active=True,
            ).update(is_active=False)

            return self.create(
                content_type=ct,
                object_id=subject.pk,
                source=source,
                user=user,
                field_name=field_name,
                claim_key=claim_key,
                value=value,
                citation=citation,
                license=license,
                changeset=changeset,
            )


class Claim(models.Model):
    """A single fact asserted by a Source or User about any catalog entity.

    Uses a GenericForeignKey (``subject``) so claims can target any model:
    MachineModel, Manufacturer, Person, etc.

    Exactly one of ``source`` or ``user`` must be set — enforced by a
    CheckConstraint and by ClaimManager.assert_claim().
    """

    content_type_id: int
    source_id: int | None
    user_id: int | None
    license_id: int | None
    changeset_id: int | None
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
        null=True,
        blank=True,
        help_text="Optional grouping of claims from a single edit session.",
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

    objects: ClassVar[ClaimManager] = ClaimManager()

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id", "field_name"]),
            models.Index(fields=["content_type", "object_id", "claim_key"]),
            models.Index(fields=["source", "content_type", "object_id"]),
            models.Index(fields=["user", "content_type", "object_id"]),
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
