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

from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.validation import (
    DIRECT,
    RELATIONSHIP,
    UNRECOGNIZED,
    classify_claim,
    validate_claim_value,
    validate_single_relationship_claim,
)

if TYPE_CHECKING:
    from apps.core.models import License
    from apps.provenance.models import ChangeSet


def _assert_claim(
    subject: ClaimControlledModel,
    field_name: str,
    value: object,
    citation: str = "",
    *,
    changeset: ChangeSet,
    claim_key: str = "",
    license: License | None = None,
) -> Claim:
    """Create a claim, deactivating any existing active claim for the same claim_key+author.

    ``subject`` can be any model instance (MachineModel, Manufacturer, Person, …).
    Attribution comes from the (required) ``changeset``: ``changeset.actor`` is
    the source of truth, and the matching legacy author column
    (``Claim.user`` / ``Claim.source``) is stamped from it.
    ``claim_key`` defaults to ``field_name`` for scalar claims.
    ``license`` is an optional per-claim License override (null inherits from source).
    Runs in a transaction to ensure the old claim is deactivated atomically.
    """
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

    # Model-driven legacy stamp: ``actor.backing_model`` ("user" / "source") is
    # both the reverse accessor on Actor and the legacy Claim FK field name (the
    # FKs are named after the lowercased model, so they coincide with
    # ``_meta.model_name`` by construction). ``getattr`` / ``setattr`` on a
    # model-declared relation name is sanctioned here. Dedupe now keys on
    # ``actor`` (every row is backfilled); the stamp retires at "Drop dead
    # schema" once the legacy ``user``/``source`` columns are gone.
    actor = changeset.actor
    if actor is None:
        raise ValueError(
            "ChangeSet must carry an actor (mint it via record_changeset)."
        )
    legacy_field = actor.backing_model
    backing = getattr(actor, legacy_field)

    ct = ContentType.objects.get_for_model(subject)
    with transaction.atomic():
        # One active claim per actor per claim_key on this subject — backed by
        # the unified provenance_unique_active_claim_per_actor index. Equivalent
        # to the old legacy-author dedupe (actor maps 1:1 to its backing record),
        # so the still-live per-user / per-source indexes stay satisfied too.
        Claim.objects.filter(
            content_type=ct,
            object_id=subject.pk,
            claim_key=claim_key,
            is_active=True,
            actor=actor,
        ).update(is_active=False)

        return Claim.objects.create(
            content_type=ct,
            object_id=subject.pk,
            actor=actor,
            field_name=field_name,
            claim_key=claim_key,
            value=value,
            citation=citation,
            license=license,
            changeset=changeset,
            **{legacy_field: backing},
        )
