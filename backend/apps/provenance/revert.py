"""Per-field claim revert logic, plus whole-ChangeSet undo.

Two inverse operations live here:

* :func:`execute_revert` deactivates **one** user claim. This is what
  surfaces on the edit-history page as a per-field Revert button.
* :func:`execute_undo_changeset` atomically inverts **every** claim in a
  single DELETE ChangeSet. This is what powers the post-delete Undo toast —
  one click restores a Title plus every cascaded Model in one unit of work.

Keeping them separate protects the per-claim contract (validation,
ownership, blast radius) from the different eligibility rules that apply
to a whole-changeset undo.
"""

from __future__ import annotations

from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.authz.exceptions import PolicyDeniedError
from apps.core.authz.types import DenialCode, Deny
from apps.core.types import EntityKey

from .changeset_writer import record_changeset
from .constants import REVERT_OTHERS_MIN_EDITS
from .models import ChangeSet, ChangeSetAction, Claim, ClaimControlledModel
from .resolution import resolve_after_mutation


class RevertError(Exception):
    """Domain error raised by execute_revert().

    Carries a ``status_code`` so the calling view can translate to the
    appropriate HTTP response without coupling revert logic to Django Ninja.
    """

    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def execute_revert(
    entity: ClaimControlledModel, *, claim_id: int, user: User, note: str
) -> None:
    """Deactivate a single user claim and re-resolve the entity.

    Creates a new ChangeSet recording the revert, deactivates the target
    claim, and delegates to ``resolve_after_mutation()`` for resolution
    and cache invalidation.

    If the same user had a previous (superseded) claim for the same
    claim_key, it is re-activated so the field falls back to their
    prior value rather than dropping to the source default.

    Raises ``RevertError`` on validation failures (bad note, missing
    claim, source-attributed, already inactive) and ``PolicyDeniedError``
    when the caller lacks authorization (sub-threshold edit count for
    reverting another user's claim). Endpoint callers let the policy
    error propagate to the global ``StructuredApiError`` handler.
    """
    if not note or not note.strip():
        raise RevertError("A note is required when reverting.")

    ct = ContentType.objects.get_for_model(entity)

    try:
        target = Claim.objects.get(pk=claim_id, content_type=ct, object_id=entity.pk)
    except Claim.DoesNotExist:
        raise RevertError("Claim not found for this entity.", status_code=404) from None

    if target.source_id is not None:
        raise RevertError("Source-attributed claims cannot be reverted.")
    # source_id XOR user_id is enforced by ``provenance_claim_source_xor_user``;
    # the source_id check above implies user_id is set.
    assert target.user_id is not None

    if not target.is_active:
        raise RevertError("This claim is already inactive.")

    if target.user_id != user.pk:
        edit_count = ChangeSet.objects.filter(user=user).count()
        if edit_count < REVERT_OTHERS_MIN_EDITS:
            raise PolicyDeniedError(
                Deny(
                    DenialCode.EXPERIENCE_REQUIRED,
                    context={
                        "required": REVERT_OTHERS_MIN_EDITS,
                        "current": edit_count,
                    },
                )
            )

    try:
        with transaction.atomic():
            cs = record_changeset(
                actor=user.actor, action=ChangeSetAction.REVERT, note=note
            )
            target.is_active = False
            target.retracted_by_changeset = cs
            target.save(update_fields=["is_active", "retracted_by_changeset"])

            # Re-activate the most recent superseded (not retracted) claim
            # from the same user for the same claim_key.  Without this,
            # reverting a user's latest edit would leave ALL their previous
            # edits for the field inactive (because _assert_claim deactivates
            # the predecessor when creating a new claim).
            predecessor = (
                Claim.objects.filter(
                    content_type=ct,
                    object_id=entity.pk,
                    user_id=target.user_id,
                    claim_key=target.claim_key,
                    is_active=False,
                    retracted_by_changeset__isnull=True,
                )
                .exclude(pk=target.pk)
                .order_by("-created_at", "-pk")
                .first()
            )
            if predecessor:
                predecessor.is_active = True
                predecessor.save(update_fields=["is_active"])

            resolve_after_mutation(entity, field_names=[target.field_name])
    except ValidationError as exc:
        raise RevertError("; ".join(exc.messages)) from exc
    except IntegrityError as exc:
        raise RevertError(f"Unique constraint violation: {exc}") from exc


class UndoError(Exception):
    """Domain error raised by :func:`execute_undo_changeset`.

    Always renders as 422 in the API layer — authorization denials
    flow through ``PolicyDeniedError`` from the policy engine, not
    through this exception.
    """


def execute_undo_changeset(
    changeset: ChangeSet, *, user: User, note: str = ""
) -> ChangeSet:
    """Atomically invert every claim in a DELETE *changeset*.

    Creates a new ``REVERT`` ChangeSet, deactivates each claim in the
    target, re-activates the most recent user predecessor per ``claim_key``
    so each field falls back to its prior user value, and re-resolves every
    affected entity.

    Eligibility:

    * Must be a user-authored ChangeSet (``user_id`` set).
    * Must have ``action = DELETE``. Per-claim reverts of EDIT ChangeSets
      use :func:`execute_revert`; CREATE undo (symmetric \u201cmake it as if
      the record was never created\u201d) is deferred \u2014 it requires extra
      machinery to handle the row columns written alongside the claims.
    * Every claim in the target must still be ``is_active=True``. If any
      have been superseded by a later user action, the ChangeSet is no
      longer the latest action and Undo is refused.

    Author-only enforcement is the policy's job (``changeset.undo`` rule
    with ``is_changeset_author``); the endpoint runs ``enforce()`` before
    calling this function. Other users use per-claim revert from edit
    history.

    Returns the newly-created REVERT ChangeSet.
    """
    if changeset.user_id is None:
        raise UndoError("Only user changesets can be undone.")
    if changeset.action != ChangeSetAction.DELETE:
        raise UndoError(
            "Only delete changesets can be undone via this endpoint. "
            "Edit changesets are reverted per-claim from edit history."
        )

    claims = list(changeset.claims.all())
    if not claims:
        raise UndoError("This changeset has no claims to undo.")

    inactive = [c for c in claims if not c.is_active]
    if inactive:
        raise UndoError(
            "This delete is no longer the latest action on every affected "
            "field. Use edit history to restore individual fields."
        )

    affected_fields: dict[EntityKey, set[str]] = defaultdict(set)
    try:
        with transaction.atomic():
            new_cs = record_changeset(
                actor=user.actor, action=ChangeSetAction.REVERT, note=note
            )
            for claim in claims:
                claim.is_active = False
                claim.retracted_by_changeset = new_cs
                claim.save(update_fields=["is_active", "retracted_by_changeset"])
                affected_fields[EntityKey(claim.content_type_id, claim.object_id)].add(
                    claim.field_name
                )

                # Re-activate the most recent superseded (but not retracted)
                # claim from the same user for the same claim_key, so the
                # field falls back to their prior value rather than dropping
                # to the source default. Mirrors execute_revert() semantics.
                # Skip any source-authored claims defensively — predecessor
                # restoration is a user-edit concept; the DB XOR constraint
                # makes ``user_id`` non-null whenever ``source_id`` is null.
                if claim.user_id is None:
                    continue
                predecessor = (
                    Claim.objects.filter(
                        content_type_id=claim.content_type_id,
                        object_id=claim.object_id,
                        user_id=claim.user_id,
                        claim_key=claim.claim_key,
                        is_active=False,
                        retracted_by_changeset__isnull=True,
                    )
                    .exclude(pk=claim.pk)
                    .order_by("-created_at", "-pk")
                    .first()
                )
                if predecessor:
                    predecessor.is_active = True
                    predecessor.save(update_fields=["is_active"])

            for key, fields in affected_fields.items():
                ct = ContentType.objects.get_for_id(key.content_type_id)
                entity = ct.get_object_for_this_type(pk=key.object_id)
                # ContentType.get_object_for_this_type returns Model; by
                # construction the affected entity carries claims, so it is
                # always a ClaimControlledModel.
                assert isinstance(entity, ClaimControlledModel)
                resolve_after_mutation(entity, field_names=list(fields))
    except ValidationError as exc:
        raise UndoError("; ".join(exc.messages)) from exc
    except IntegrityError as exc:
        raise UndoError(f"Unique constraint violation: {exc}") from exc

    return new_cs
