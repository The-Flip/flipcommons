"""Claim computation — leaf module shared by the live and dry-run paths.

The middle of the pipeline: turn planned assertions into unsaved ``Claim`` rows
(:func:`_build_claims`), validate their values (:func:`_validate_fail_fast` for
the live path, :func:`_validate_and_collect_errors` for dry-run), and diff them
against the source's existing active claims (:func:`_diff_claims`). Also resolves
explicit retractions to live claim PKs (:func:`_process_retractions`) and houses
the shared provenance empty-diff guard (:func:`_reject_empty_diff_provenance`).

These functions are called across the live and dry-run paths (:mod:`.orchestrate`,
:mod:`.dry_run`, :mod:`.persist`), so they live in a leaf with no intra-package
dependencies. ``RetractEntry`` — the apply-time carrier ``_process_retractions``
produces and :mod:`.persist` consumes — is defined here, next to its producer.
"""

from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple

from django.core.exceptions import ValidationError

from apps.catalog.ingestion.plan import (
    EntryIndex,
    IngestPlan,
    PlannedClaimAssert,
    PlannedClaimRetract,
    RunReport,
)
from apps.core.models import LIFECYCLE_STATUS_FIELD
from apps.core.types import ClaimIdentity
from apps.provenance.models import Claim, ExistingClaimRow, Source
from apps.provenance.validation import validate_claims_batch


class RetractEntry(NamedTuple):
    """An active claim targeted for retraction."""

    pk: int
    content_type_id: int
    object_id: int
    # Patch runs only: the file-order index of the entry that authored this
    # retraction, used by ``_persist`` to group retractions into per-entry
    # ChangeSets. ``None`` for non-patch runs (IPDB/OPDB never retract).
    entry_index: EntryIndex | None = None


def _build_claims(
    assertions: list[PlannedClaimAssert],
    source: Source,
) -> list[Claim]:
    """Convert planned assertions to unsaved Claim instances (deduplicated).

    Last-write-wins per ``(content_type_id, object_id, claim_key)``.
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
            source=source,
            license_id=pca.license_id,
        )
        seen[ClaimIdentity(content_type_id, object_id, claim_key)] = claim
    return list(seen.values())


def _validate_fail_fast(
    all_claims: list[Claim],
    report: RunReport,
) -> list[Claim]:
    """Validate claims.  Raises ``ValidationError`` if any are rejected."""
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


def _validate_and_collect_errors(
    claims: list[Claim],
    report: RunReport,
) -> list[Claim]:
    """Validate claims for dry-run (non-fatal).  Appends errors to report."""
    valid, rejected_count = validate_claims_batch(claims)
    if rejected_count > 0:
        valid_ids = {id(c) for c in valid}
        for c in claims:
            if id(c) not in valid_ids:
                report.errors.append(
                    f"Invalid claim: {c.field_name} on "
                    f"ct={c.content_type_id} obj={c.object_id}"
                )
        report.rejected += rejected_count
    return valid


def _diff_claims(
    valid_claims: list[Claim],
    source: Source,
) -> tuple[list[Claim], list[int]]:
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
            source=source,
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
    superseded_ids: list[int] = []

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
            source=source,
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


def _reject_empty_diff_provenance(plan: IngestPlan, changed: set[EntryIndex]) -> None:
    """Reject a provenance-bearing patch entry absent from *changed* (decision 3).

    A patch entry carrying a ``note``/``cite``/``cites`` (or a ``retract:`` +
    ``note:``) that diffs to nothing would silently discard that provenance — no
    ChangeSet is minted for it, so the note/citation just vanishes. Tightening
    today's silent re-assert no-op into a hard error keeps provenance honest.

    ``changed`` is the set of entry indexes that produced — or, in dry-run, are
    *assumed* to produce — a real claim change. Both paths share this rejection;
    they differ only in how ``changed`` is built (the live path diffs every
    assertion; dry-run can't diff its carve-outs, so it treats new-inline-cite /
    deferred / FK-to-planned assertions as changed).

    Delete entries are exempt: an idempotent re-delete of an already-deleted
    entity diffs to a clean no-op by design. A delete emits only ``status``
    claims, so an entry whose assertions are *all* ``LIFECYCLE_STATUS_FIELD`` is a
    delete — detected model-drivenly here, since the entry kind isn't threaded
    into the apply engine.

    Patch-only (``patch_id`` set); non-patch runs carry no per-entry provenance.
    Raises ``ValidationError`` (the apply engine is source-agnostic and must not
    import ``PatchError``); ``_apply_one`` converts it to a clean ``PatchError``.
    """
    if plan.patch_id is None:
        return

    # Per entry: which carry provenance, and which are a pure delete (all-status,
    # exempt because an idempotent re-delete is a clean no-op by design).
    has_provenance: set[EntryIndex] = set()
    only_status: dict[EntryIndex, bool] = {}
    for pca in plan.assertions:
        idx = pca.entry_index
        assert idx is not None  # patch assertions are always stamped
        if pca.note or pca.citation_ref is not None or pca.inline_cites:
            has_provenance.add(idx)
        is_status = pca.field_name == LIFECYCLE_STATUS_FIELD
        only_status[idx] = only_status.get(idx, True) and is_status
    # The ``pcr.note`` branch is defensive: a no-op retraction (already-inactive
    # field) never reaches here — build-time ``_check_provenance_carrier`` rejects
    # a ``retract:`` + ``note:`` with no carrier — and a real retraction always
    # yields a ``RetractEntry``, so its ``entry_index`` is already in ``changed``.
    # Kept so the rule "a note must attach to a change" holds regardless of layer.
    for pcr in plan.retractions:
        idx = pcr.entry_index
        assert idx is not None
        if pcr.note:
            has_provenance.add(idx)
        only_status[idx] = False  # a retraction means the entry isn't a delete

    for idx in has_provenance:
        if only_status.get(idx, False) or idx in changed:
            continue
        raise ValidationError(
            f"Patch entry at index {idx} carries a note/citation but changes "
            f"nothing (its value already matches) — remove the no-op entry or "
            f"correct its value so the provenance attaches to a real change"
        )
