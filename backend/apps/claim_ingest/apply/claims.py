"""Claim computation — leaf module for the pipeline's middle stage.

Turn planned assertions into unsaved ``Claim`` rows (:func:`_build_claims`),
validate their values (:func:`_validate_claims`), and diff them against the
source's existing active claims (:func:`_diff_claims`). Also resolves explicit
retractions to live claim PKs (:func:`_process_retractions`).

These functions are called from :mod:`.orchestrate` and :mod:`.persist`, so they
live in a leaf with no intra-package dependencies. ``RetractEntry`` — the
apply-time carrier ``_process_retractions`` produces and :mod:`.persist`
consumes — is defined here, next to its producer.
"""

from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple

from django.core.exceptions import ValidationError

from apps.claim_ingest.plan import (
    EntryIndex,
    PlannedClaimAssert,
    PlannedClaimRetract,
    RunReport,
)
from apps.core.types import ClaimIdentity
from apps.provenance.models import Claim, ExistingClaimRow, Source
from apps.provenance.types import ClaimId
from apps.provenance.validation import validate_claims_batch


class RetractEntry(NamedTuple):
    """An active claim targeted for retraction."""

    pk: int
    content_type_id: int
    object_id: int
    # The file-order index of the entry that authored this retraction, used by
    # ``_persist`` to group retractions into per-entry ChangeSets. ``None`` only
    # transiently before the front end's second pass stamps it.
    entry_index: EntryIndex | None = None


def _build_claims(
    assertions: list[PlannedClaimAssert],
) -> list[Claim]:
    """Convert planned assertions to unsaved Claim instances (deduplicated).

    Last-write-wins per ``(content_type_id, object_id, claim_key)``. Attribution
    (``actor``) is stamped at persist time from the ChangeSet, not here.
    """
    seen: dict[ClaimIdentity, Claim] = {}
    for pca in assertions:
        claim_key = pca.claim_key or pca.field_name
        content_type_id = pca.content_type_id
        object_id = pca.object_id
        assert content_type_id is not None
        assert object_id is not None
        claim = Claim(
            content_type_id=content_type_id,
            object_id=object_id,
            field_name=pca.field_name,
            claim_key=claim_key,
            value=pca.value,
            license_id=pca.license_id,
        )
        seen[ClaimIdentity(content_type_id, object_id, claim_key)] = claim
    return list(seen.values())


def _validate_claims(
    all_claims: list[Claim],
    report: RunReport,
) -> list[Claim]:
    """Validate claims.  Raises ``ValidationError`` if any are rejected.

    Fail-fast but exhaustive: every invalid claim is appended to
    ``report.errors`` before the raise, so the failed ``IngestRun`` records all
    data-quality issues in one run.
    """
    valid, rejected_count = validate_claims_batch(all_claims)
    if rejected_count > 0:
        valid_ids = {id(c) for c in valid}
        for c in all_claims:
            if id(c) not in valid_ids:
                report.errors.append(
                    f"Invalid claim: {c.field_name} on "
                    f"ct={c.content_type_id} obj={c.object_id}"
                )
        report.rejected = rejected_count
        raise ValidationError(f"{rejected_count} claim(s) failed validation")
    return valid


def _diff_claims(
    valid_claims: list[Claim],
    source: Source,
) -> tuple[list[Claim], list[ClaimId]]:
    """Compare valid claims against existing active claims from the source.

    Returns ``(to_create, superseded_ids)`` where *superseded_ids* are PKs
    of existing claims deactivated because their value changed.
    """
    by_ct: dict[int, set[int]] = defaultdict(set)
    for c in valid_claims:
        by_ct[c.content_type_id].add(c.object_id)

    existing: dict[ClaimIdentity, ExistingClaimRow] = {}
    for ct_id, obj_ids in by_ct.items():
        for row in Claim.objects.filter(
            actor_id=source.actor_id,
            is_active=True,
            content_type_id=ct_id,
            object_id__in=obj_ids,
        ).values_list(
            "pk",
            "content_type_id",
            "object_id",
            "claim_key",
            "value",
            "license_id",
        ):
            pk, ct, oid, ck, val, lic_id = row
            existing[ClaimIdentity(ct, oid, ck)] = ExistingClaimRow(
                value=val,
                license_id=lic_id,
                pk=pk,
            )

    to_create: list[Claim] = []
    superseded_ids: list[ClaimId] = []

    for claim in valid_claims:
        key = ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key)
        old = existing.get(key)
        if old:
            if old.value == claim.value and old.license_id == claim.license_id:
                continue
            superseded_ids.append(old.pk)
        to_create.append(claim)

    return to_create, superseded_ids


def _process_retractions(
    retractions: list[PlannedClaimRetract],
    source: Source,
    report: RunReport,
) -> list[RetractEntry]:
    """Find active claims targeted by explicit retractions."""
    if not retractions:
        return []

    retract_keys: dict[ClaimIdentity, PlannedClaimRetract] = {
        ClaimIdentity(r.content_type_id, r.object_id, r.claim_key): r
        for r in retractions
    }

    by_ct: dict[int, set[int]] = defaultdict(set)
    for identity in retract_keys:
        by_ct[identity.content_type_id].add(identity.object_id)

    found: dict[ClaimIdentity, int] = {}
    for ct_id, obj_ids in by_ct.items():
        for pk, c_ct, c_oid, c_ck in Claim.objects.filter(
            actor_id=source.actor_id,
            is_active=True,
            content_type_id=ct_id,
            object_id__in=obj_ids,
        ).values_list("pk", "content_type_id", "object_id", "claim_key"):
            key = ClaimIdentity(c_ct, c_oid, c_ck)
            if key in retract_keys:
                found[key] = pk

    retract_entries: list[RetractEntry] = []
    for key in retract_keys:
        found_pk = found.get(key)
        if found_pk is not None:
            retract_entries.append(
                RetractEntry(
                    found_pk,
                    key.content_type_id,
                    key.object_id,
                    retract_keys[key].entry_index,
                )
            )
        else:
            r = retract_keys[key]
            report.warnings.append(
                f"Retract target not found: claim_key={r.claim_key!r} "
                f"on ct={r.content_type_id} obj={r.object_id}"
            )

    return retract_entries
