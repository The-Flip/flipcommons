"""Dry-run path: validate and diff a plan without writing anything.

:func:`_apply_dry_run` mirrors the live path's compute steps (build → validate →
diff, via :mod:`.claims`) but commits nothing and reports validation failures
non-fatally. Its bulk is carve-outs: assertions the live path validates only
because creates run first in the same transaction — deferred relationship
claims, deferred FK claim values (``value_ref``), new inline citations — can't
be DB-validated here, so they're counted as asserted and skipped.

Depends on :mod:`.claims` for the shared build/validate/diff helpers; structural
validation already ran in :mod:`.orchestrate` before the fork. Deliberately does
**not** touch :mod:`.persist` — the dry-run path never writes.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from apps.claim_ingest.apply.claims import (
    RetractEntry,
    _build_claims,
    _diff_claims,
    _process_retractions,
    _reject_empty_diff_provenance,
    _validate_and_collect_errors,
)
from apps.claim_ingest.plan import (
    EntryIndex,
    Handle,
    IngestPlan,
    PlannedClaimAssert,
    RunReport,
)
from apps.core.types import ClaimIdentity
from apps.provenance.models import Claim


def _apply_dry_run(plan: IngestPlan, report: RunReport) -> RunReport:
    """Read-only path: validate and diff without writing anything."""
    report.records_created = len(plan.entities)

    # Preview committed-state conflicts the live pre-write hooks would warn on at
    # apply (a citation source whose recognition hosts span >1 root). Read-only
    # and dry-run-only — the live path runs the authoritative pre_write_hooks
    # instead, so neither path double-warns. Opaque to the apply layer.
    for hook in plan.dry_run_preview_hooks:
        hook(report)

    # Deferred relationship claims (identity_refs) cannot be validated
    # in dry-run — the relationship validation layer checks that
    # referenced PKs exist in the DB, but those entities are only
    # planned.  Count them toward asserted but skip claim validation.
    # Structural correctness (namespace, handle existence) is already
    # verified by _validate_assertion_targets().
    deferred = [p for p in plan.assertions if p.relationship_namespace]
    concrete = [p for p in plan.assertions if not p.relationship_namespace]

    report.asserted += len(deferred)

    # New-handle inline citations can't validate in dry-run: nothing is minted,
    # so ``convert_authoring_to_storage`` would raise ``Cite not found`` on the
    # unminted slug. Carve the whole assertion out — count asserted, skip
    # validate/diff — mirroring the value_ref carve-out below, across BOTH
    # the existing-entity and planned-entity sub-paths. Whole-assertion: a
    # description mixing new handles with existing slugs loses dry-run validation
    # of its existing-slug portion too. Correspondence + spec parse already ran at
    # process time, so structural errors still surfaced. (Existing-slug-only
    # assertions carry no ``inline_cites`` and stay on the standard path; real
    # validation of new cites is the snapshot+apply loop.)
    new_inline_cite_ids = {id(p) for p in concrete if p.inline_cites}
    report.asserted += len(new_inline_cite_ids)

    # Deferred direct-FK claim values (``value_ref``) cannot be validated in
    # dry-run — the claim value is the target's PK, but the target is only
    # planned (the live path fills the PK in after the bulk-create). Count
    # them asserted, skip validation/diff. Structural correctness (handle
    # existence, value/value_ref exclusivity) is already verified by
    # _validate_assertion_targets().
    value_ref_ids = {id(p) for p in concrete if p.value_ref is not None}
    report.asserted += len(value_ref_ids)

    # Claims targeting existing entities: validate + diff.
    existing_assertions = [
        p
        for p in concrete
        if p.handle is None
        and id(p) not in value_ref_ids
        and id(p) not in new_inline_cite_ids
    ]
    # Entry indexes whose existing-entity claim survives the diff (a real change),
    # for the dry-run empty-diff guard below. Carve-outs are added separately.
    existing_changed: set[EntryIndex] = set()
    if existing_assertions:
        claims = _build_claims(existing_assertions)
        valid = _validate_and_collect_errors(claims, report)
        if valid:
            to_create, superseded_ids = _diff_claims(valid, plan.source)
            report.asserted += len(to_create)
            report.unchanged += len(valid) - len(to_create)
            report.superseded += len(superseded_ids)
            idx_by_identity: dict[ClaimIdentity, EntryIndex | None] = {}
            for p in existing_assertions:
                # Existing-entity assertions (handle is None) carry concrete ct/obj.
                assert p.content_type_id is not None
                assert p.object_id is not None
                key = ClaimIdentity(
                    p.content_type_id, p.object_id, p.claim_key or p.field_name
                )
                idx_by_identity[key] = p.entry_index
            for claim in to_create:
                idx = idx_by_identity.get(
                    ClaimIdentity(
                        claim.content_type_id, claim.object_id, claim.claim_key
                    )
                )
                if idx is not None:
                    existing_changed.add(idx)

    # Claims targeting planned entities: validate only (all are new by
    # definition).  Build sentinel claims without mutating the plan.
    planned_assertions = [
        p
        for p in concrete
        if p.handle is not None
        and id(p) not in value_ref_ids
        and id(p) not in new_inline_cite_ids
    ]
    if planned_assertions:
        handle_to_ct: dict[Handle, int] = {
            e.handle: ContentType.objects.get_for_model(e.model_class).pk
            for e in plan.entities
        }

        def _sentinel(pca: PlannedClaimAssert) -> Claim:
            assert pca.handle is not None
            return Claim(
                content_type_id=handle_to_ct[pca.handle],
                object_id=0,
                field_name=pca.field_name,
                claim_key=pca.claim_key or pca.field_name,
                value=pca.value,
                actor_id=plan.source.actor_id,
                license_id=pca.license_id,
            )

        sentinel_claims = [_sentinel(pca) for pca in planned_assertions]
        valid = _validate_and_collect_errors(sentinel_claims, report)
        report.asserted += len(valid)

    # Retractions: verify targets exist, count.
    retract_entries: list[RetractEntry] = []
    if plan.retractions:
        retract_entries = _process_retractions(plan.retractions, plan.source, report)
        report.retracted = len(retract_entries)

    # Empty-diff guard (decision 3), same as the live path but with a dry-run
    # ``changed`` set: assertions this path can't diff — carve-outs (deferred,
    # new-inline-cite, value_ref) and creates/companions (handle-targeted) —
    # are *assumed* to change; existing-entity assertions count only when their
    # claim survived the diff above. So a plain unchanged-value-with-note entry is
    # rejected at --dry-run too, not only at apply.
    #
    # Skip when validation already collected errors: a rejected (invalid) claim
    # never reaches ``changed``, so the guard would misreport it as a no-op and
    # mask the real validation error. Live is immune — ``_validate_fail_fast``
    # raises before the guard — so this keeps dry-run's diagnostic priority equal.
    if not report.errors:
        changed = set(existing_changed)
        for p in plan.assertions:
            assert p.entry_index is not None
            if (
                p.relationship_namespace  # deferred member
                or p.handle is not None  # create or its companion edits
                or p.inline_cites  # new inline citation
                or p.value_ref is not None  # FK → same-plan create
            ):
                changed.add(p.entry_index)
        for entry in retract_entries:
            assert entry.entry_index is not None
            changed.add(entry.entry_index)
        _reject_empty_diff_provenance(plan, changed)

    return report
