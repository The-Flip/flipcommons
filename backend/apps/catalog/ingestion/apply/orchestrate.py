"""The orchestrator: ``apply_plan`` drives one ingest plan through the pipeline.

Wires the package's stages in order — structural validation (:mod:`.validate`),
the live/dry-run fork (:mod:`.dry_run`), then for the live path: entity creation +
claim build/diff (:mod:`.persist`, :mod:`.claims`) and persistence inside one
transaction, with the ``IngestRun`` audit row created *outside* it so a failure
survives rollback. This module owns transaction structure and run bookkeeping
only; the per-stage logic lives in the leaf modules.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.catalog.ingestion.apply.claims import (
    _build_claims,
    _diff_claims,
    _process_retractions,
    _validate_fail_fast,
)
from apps.catalog.ingestion.apply.dry_run import _apply_dry_run
from apps.catalog.ingestion.apply.persist import (
    _attach_plan_citations,
    _check_empty_diff_entries,
    _collect_plan_provenance,
    _create_entities,
    _materialize_inline_citations,
    _patch_handles,
    _persist,
    _resolve,
)
from apps.catalog.ingestion.apply.validate import (
    _validate_assertion_targets,
    _validate_entity_claim_consistency,
    _validate_entry_index_stamping,
    _validate_handle_refs,
)
from apps.catalog.ingestion.plan import IngestPlan, RunReport
from apps.provenance.models import IngestRun


def apply_plan(plan: IngestPlan, *, dry_run: bool = False) -> RunReport:
    """Execute an ingest plan.  See package docstring for full contract."""
    report = RunReport()
    report.warnings.extend(plan.warnings)

    # ── Structural validation (before any DB writes) ──────────────
    _validate_entity_claim_consistency(plan)
    _validate_assertion_targets(plan)
    _validate_handle_refs(plan)
    # Before the live/dry-run split, so a mis-stamped patch fails at --dry-run too.
    _validate_entry_index_stamping(plan)

    if dry_run:
        return _apply_dry_run(plan, report)

    # ── Create IngestRun outside transaction ──────────────────────
    # Created outside so a FAILED run survives rollback — that's exactly
    # when the audit record matters most. The SUCCESS flip, by contrast,
    # commits *inside* the transaction (below): "applied" must be atomic
    # with the claims, or a torn write leaves a half-applied patch that a
    # retry can't safely re-run (creates re-hit existing rows, expect
    # guards re-evaluate against mutated state).
    run = IngestRun.objects.create(
        source=plan.source,
        input_fingerprint=plan.input_fingerprint,
        patch_id=plan.patch_id,
        note=plan.note,
    )

    try:
        with transaction.atomic():
            # Pre-write hooks run first so anything they create (e.g. a citation
            # source root) is visible to the rest of the transaction — notably to
            # _attach_plan_citations resolving a same-patch cite: URL. They bump
            # report counters / warnings directly.
            for hook in plan.pre_write_hooks:
                hook(report)

            handle_map = _create_entities(plan.entities)
            report.records_created = len(plan.entities)

            _patch_handles(plan.assertions, handle_map)
            # Mint new inline-citation footnotes and rewrite their handle markers
            # to minted slugs *before* claims are built/validated, so the standard
            # markdown conversion in _validate_fail_fast resolves them to storage
            # form. Existing-slug markers self-resolve and aren't touched here.
            _materialize_inline_citations(plan.assertions)
            # Per-claim provenance (note/citation) carried by the plan, collected
            # once now that handles are resolved (so every assertion carries its
            # real ct/obj). Kept out of _build_claims so that helper's signature —
            # and its dry-run call site — stay untouched.
            entry_notes, claim_citations, claim_entry_index = _collect_plan_provenance(
                plan
            )
            all_claims = _build_claims(plan.assertions, plan.source)
            valid_claims = _validate_fail_fast(all_claims, report)

            to_create, superseded_ids = _diff_claims(valid_claims, plan.source)
            report.asserted = len(to_create)
            report.unchanged = len(valid_claims) - len(to_create)
            report.superseded = len(superseded_ids)

            retract_entries = _process_retractions(
                plan.retractions,
                plan.source,
                report,
            )
            report.retracted = len(retract_entries)

            # A provenance-bearing patch entry that diffs to no change would
            # silently drop its note/citation — reject it (delete entries exempt).
            _check_empty_diff_entries(
                plan, to_create, retract_entries, claim_entry_index
            )

            _persist(
                run,
                to_create,
                superseded_ids,
                retract_entries,
                entry_notes,
                claim_entry_index,
            )
            _attach_plan_citations(to_create, claim_citations)
            _resolve(to_create, retract_entries, plan.resolve_hooks)

            # SUCCESS flip inside the transaction — see note above. The
            # partial unique index on (patch_id) WHERE status='success'
            # is enforced here; a racing second application raises
            # IntegrityError, which the caller treats as "already applied".
            run.status = IngestRun.Status.SUCCESS
            run.records_parsed = plan.records_parsed
            run.records_matched = plan.records_matched
            run.records_created = report.records_created
            run.claims_asserted = report.asserted
            run.claims_retracted = report.retracted
            run.citation_sources_created = report.sources_created
            run.citation_source_links_created = report.source_links_created
            run.warnings = report.warnings
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "records_parsed",
                    "records_matched",
                    "records_created",
                    "claims_asserted",
                    "claims_retracted",
                    "citation_sources_created",
                    "citation_source_links_created",
                    "warnings",
                    "finished_at",
                ],
            )

    except Exception as exc:
        run.status = IngestRun.Status.FAILED
        run.claims_rejected = report.rejected
        run.errors = report.errors if report.errors else [str(exc)]
        run.finished_at = timezone.now()
        run.save(
            update_fields=["status", "claims_rejected", "errors", "finished_at"],
        )
        raise

    return report
