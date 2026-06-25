"""The single claim-mint primitive, ``_assert_claim``.

It's one of two sanctioned places a ``Claim`` is persisted (the other being
the bulk ingest path in ``claim_ingest/apply/persist.py``).

Why here instead of on a custom manager?  Because in the provenance app's internal
stack, this function lives above ``models`` and ``validation``; a module-level function keeps
the chokepoint nameable by the import graph, and lets ``validation`` import at
module scope (a clean downward edge) instead of the lazy import a manager method
on ``models.claim`` would be forced into.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from apps.provenance.models import ChangeSet, Claim, ClaimControlledModel, Source
from apps.provenance.validation import (
    DIRECT,
    RELATIONSHIP,
    UNRECOGNIZED,
    classify_claim,
    validate_claim_value,
    validate_single_relationship_claim,
)

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.core.models import License


def _assert_claim(
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
    ``changeset`` groups this claim with others; it is **required** for
    user-attributed claims (every user write is an attributed ChangeSet)
    and optional for source-attributed (ingest) claims.
    Runs in a transaction to ensure the old claim is deactivated atomically.
    """
    if (source is None) == (user is None):
        raise ValueError("Exactly one of source or user must be provided.")
    if user is not None and changeset is None:
        raise ValueError(
            "A user-attributed claim requires a changeset "
            "(every user write must be an attributed ChangeSet)."
        )
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
        Claim.objects.filter(
            content_type=ct,
            object_id=subject.pk,
            source=source,
            user=user,
            claim_key=claim_key,
            is_active=True,
        ).update(is_active=False)

        return Claim.objects.create(
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
