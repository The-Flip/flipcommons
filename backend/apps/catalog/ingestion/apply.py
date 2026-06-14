"""Apply layer: source-agnostic engine for executing ingest plans.

Processes three explicit primitives — ``create_entity``,
``assert_claim``, ``retract_claim`` — in one transaction.  Contains no
source-specific logic.

Design decisions that look like bugs but aren't:

- ``IngestRun`` is created **outside** the transaction so it survives
  rollback.  A failed run is exactly when you most want the audit record.
- Structural plan errors (bad handles, missing assertions) raise
  **before** ``IngestRun`` creation — they're adapter bugs, not data
  issues, and shouldn't leave audit debris.
- Validation is fail-fast but **exhaustive**: all invalid claims are
  collected before raising, so one run surfaces every data quality issue.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple, cast

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.catalog.ingestion.plan import (
    CitationRef,
    CiteHandle,
    EntryIndex,
    IngestPlan,
    PlannedClaimAssert,
    PlannedClaimRetract,
    PlannedEntityCreate,
    ResolveHook,
    RunReport,
)
from apps.core.models import LIFECYCLE_STATUS_FIELD
from apps.core.types import ClaimIdentity, EntityKey
from apps.provenance.models import (
    ChangeSet,
    Claim,
    ClaimControlledModel,
    ExistingClaimRow,
    IngestRun,
    Source,
)
from apps.provenance.validation import validate_claims_batch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine-internal carriers
# ---------------------------------------------------------------------------
# Apply-time intermediates — produced and consumed within this module, never
# part of the plan an adapter builds (those live in ``ingestion.plan``).


class RetractEntry(NamedTuple):
    """An active claim targeted for retraction."""

    pk: int
    content_type_id: int
    object_id: int
    # Patch runs only: the file-order index of the entry that authored this
    # retraction, used by ``_persist`` to group retractions into per-entry
    # ChangeSets. ``None`` for non-patch runs (IPDB/OPDB never retract).
    entry_index: EntryIndex | None = None


# Per-entry / per-claim provenance maps produced by ``_collect_plan_provenance``
# and consumed by ``_persist`` / ``_attach_plan_citations``. ``EntryNotes`` keys
# each entry's note by its ``EntryIndex`` (one ChangeSet, one note per patch
# entry); ``ClaimEntryIndex`` resolves a built claim back to its entry for
# per-entry ChangeSet grouping; ``ClaimCitations`` keys per claim identity.
type EntryNotes = dict[EntryIndex, str]
type ClaimCitations = dict[ClaimIdentity, CitationRef]
type ClaimEntryIndex = dict[ClaimIdentity, EntryIndex]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def apply_plan(plan: IngestPlan, *, dry_run: bool = False) -> RunReport:
    """Execute an ingest plan.  See module docstring for full contract."""
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


# ---------------------------------------------------------------------------
# Structural validation (shared by live and dry-run paths)
# ---------------------------------------------------------------------------


def _validate_entity_claim_consistency(plan: IngestPlan) -> None:
    """Every claim-controlled field populated by a PlannedEntityCreate
    (via kwargs or handle_refs) must have a matching PlannedClaimAssert
    targeting the same handle."""
    from apps.provenance.models import get_claim_fields

    asserted_by_handle: dict[str, set[str]] = defaultdict(set)
    for pca in plan.assertions:
        if pca.handle is not None:
            asserted_by_handle[pca.handle].add(pca.field_name)

    for entity in plan.entities:
        claim_fields = get_claim_fields(entity.model_class)
        asserted = asserted_by_handle.get(entity.handle, set())

        # Check kwargs (e.g. "name", "slug").
        for kwarg_name in entity.kwargs:
            if kwarg_name in claim_fields and kwarg_name not in asserted:
                raise ValueError(
                    f"PlannedEntityCreate(handle={entity.handle!r}) populates "
                    f"claim-controlled field {kwarg_name!r} but no matching "
                    f"PlannedClaimAssert exists for that handle and field."
                )

        # Check handle_refs (e.g. "manufacturer_id" → claim field "manufacturer").
        # handle_refs keys use the column name (attname); claim fields use
        # the Django field name.  Resolve via model _meta.
        for ref_kwarg in entity.handle_refs:
            field_name = _attname_to_field_name(entity.model_class, ref_kwarg)
            if field_name in claim_fields and field_name not in asserted:
                raise ValueError(
                    f"PlannedEntityCreate(handle={entity.handle!r}) populates "
                    f"claim-controlled field {field_name!r} (via handle_ref "
                    f"{ref_kwarg!r}) but no matching PlannedClaimAssert "
                    f"exists for that handle and field."
                )

        # Every new entity must have status='active' for creation provenance.
        if "status" in claim_fields and entity.kwargs.get("status") != "active":
            raise ValueError(
                f"PlannedEntityCreate(handle={entity.handle!r}) must include "
                f"status='active' in kwargs"
            )


def _attname_to_field_name(
    model_class: type[models.Model],
    attname: str,
) -> str:
    """Map a Django column name (attname) to the field name.

    For FK fields, ``attname`` is e.g. ``manufacturer_id`` while the
    field name is ``manufacturer``.  For non-FK fields they are the same.
    """
    for f in model_class._meta.get_fields():
        if getattr(f, "attname", None) == attname:
            return f.name
    return attname


def _validate_handle_refs(plan: IngestPlan) -> None:
    """Every handle_ref must point to a handle that appears earlier in the list."""
    seen: set[str] = set()
    for entity in plan.entities:
        for kwarg_name, ref_handle in entity.handle_refs.items():
            if ref_handle not in seen:
                raise ValueError(
                    f"PlannedEntityCreate(handle={entity.handle!r}) has "
                    f"handle_ref {kwarg_name!r} → {ref_handle!r} but that "
                    f"handle has not been seen yet (it must appear earlier "
                    f"in the entity list)"
                )
            if kwarg_name in entity.kwargs:
                raise ValueError(
                    f"PlannedEntityCreate(handle={entity.handle!r}) has "
                    f"{kwarg_name!r} in both kwargs and handle_refs — "
                    f"use one or the other"
                )
        seen.add(entity.handle)


def _validate_entry_index_stamping(plan: IngestPlan) -> None:
    """Every assertion/retraction in a patch plan must carry an ``entry_index``.

    Patch runs group ChangeSets by ``entry_index`` (``_persist`` patch mode), so a
    missed stamp — or a hand-built ``patch_id`` plan that forgot to set one —
    would silently collapse the whole run under a single group. The patch adapter
    always stamps, so this is an internal invariant: a plain ``ValueError``, not a
    source-facing ``ValidationError``/``PatchError``. Non-patch plans
    (``patch_id is None``) group per entity and never read the index, so are exempt.
    """
    if plan.patch_id is None:
        return
    for pca in plan.assertions:
        if pca.entry_index is None:
            raise ValueError(
                f"Patch plan {plan.patch_id!r} has an assertion without an "
                f"entry_index (field={pca.field_name!r})"
            )
    for pcr in plan.retractions:
        if pcr.entry_index is None:
            raise ValueError(
                f"Patch plan {plan.patch_id!r} has a retraction without an "
                f"entry_index (claim_key={pcr.claim_key!r})"
            )


def _validate_assertion_targets(plan: IngestPlan) -> None:
    """Every assertion must target exactly one of handle or ct/obj."""
    valid_handles = {e.handle for e in plan.entities}

    # Duplicate handles.
    if len(valid_handles) != len(plan.entities):
        seen: set[str] = set()
        for e in plan.entities:
            if e.handle in seen:
                raise ValueError(
                    f"Duplicate handle {e.handle!r} in PlannedEntityCreate list"
                )
            seen.add(e.handle)

    for pca in plan.assertions:
        has_handle = pca.handle is not None
        has_target = pca.content_type_id is not None and pca.object_id is not None

        if has_handle and has_target:
            raise ValueError(
                f"PlannedClaimAssert(field_name={pca.field_name!r}) has both "
                f"a handle ({pca.handle!r}) and content_type_id/object_id — "
                f"set exactly one"
            )
        if has_handle:
            if pca.handle not in valid_handles:
                raise ValueError(
                    f"PlannedClaimAssert references unknown handle "
                    f"{pca.handle!r} (field_name={pca.field_name!r})"
                )
        elif not has_target:
            raise ValueError(
                f"PlannedClaimAssert(field_name={pca.field_name!r}) has "
                f"neither a handle nor content_type_id/object_id"
            )

        # Deferred relationship identity: mutual exclusivity.
        has_deferred = bool(pca.relationship_namespace)
        has_concrete = bool(pca.claim_key) or pca.value is not None
        if has_deferred and has_concrete:
            raise ValueError(
                f"PlannedClaimAssert(field_name={pca.field_name!r}) has both "
                f"concrete claim_key/value and relationship_namespace — "
                f"use one or the other"
            )

        # identity_refs requires relationship_namespace.
        if pca.identity_refs and not pca.relationship_namespace:
            raise ValueError(
                f"PlannedClaimAssert(field_name={pca.field_name!r}) has "
                f"identity_refs but no relationship_namespace"
            )

        # Validate identity_refs handles exist in the entity list.
        for key, ref_handle in pca.identity_refs.items():
            if ref_handle not in valid_handles:
                raise ValueError(
                    f"PlannedClaimAssert(field_name={pca.field_name!r}) "
                    f"has identity_ref {key!r} → {ref_handle!r} but that "
                    f"handle does not exist in the entity list"
                )


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------


def _planned_public_ids(
    entities: list[PlannedEntityCreate],
) -> dict[type[ClaimControlledModel], set[str]]:
    """Map each planned model class to the public_ids it will create.

    A planned entity's public_id is the value of its ``public_id_field``
    kwarg (``slug`` for most models, ``location_path`` for Location).
    """
    result: dict[type[ClaimControlledModel], set[str]] = defaultdict(set)
    for entity in entities:
        pid_field = getattr(entity.model_class, "public_id_field", "slug")
        pid = entity.kwargs.get(pid_field)
        if isinstance(pid, str):
            result[entity.model_class].add(pid)
    return result


def _fk_target_is_planned(
    subject_model: type[models.Model],
    pca: PlannedClaimAssert,
    planned: dict[type[ClaimControlledModel], set[str]],
) -> bool:
    """True if *pca* is an FK claim on *subject_model* naming a same-plan create.

    The shared core: given the subject model the claim lives on, decide whether
    the claim's value points at an entity this plan will create. Callers supply
    the subject from whatever they have — ``content_type_id`` for an
    existing-entity claim, the create handle for a planned-entity claim.
    """
    if not isinstance(pca.value, str):
        return False
    try:
        django_field = subject_model._meta.get_field(pca.field_name)
    except FieldDoesNotExist:
        return False
    if not isinstance(django_field, models.ForeignKey):
        return False
    target_model = django_field.related_model
    if not isinstance(target_model, type) or not issubclass(
        target_model, ClaimControlledModel
    ):
        return False
    return pca.value.strip() in planned.get(target_model, set())


def _fk_value_is_planned(
    pca: PlannedClaimAssert,
    planned: dict[type[ClaimControlledModel], set[str]],
) -> bool:
    """True if *pca* is an existing-entity FK claim naming a same-plan create.

    Subject model derived from ``content_type_id`` (the claim targets an existing
    row). *planned* is the precomputed ``_planned_public_ids`` map. Used only by
    the dry-run path to skip DB existence validation for FK targets that don't
    exist yet because they're created in this same plan.
    """
    if pca.content_type_id is None:
        return False
    model_class = ContentType.objects.get_for_id(pca.content_type_id).model_class()
    if model_class is None:
        return False
    return _fk_target_is_planned(model_class, pca, planned)


def _apply_dry_run(plan: IngestPlan, report: RunReport) -> RunReport:
    """Read-only path: validate and diff without writing anything."""
    report.records_created = len(plan.entities)

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
    # validate/diff — mirroring the fk-to-planned carve-outs below, across BOTH
    # the existing-entity and planned-entity sub-paths. Whole-assertion: a
    # description mixing new handles with existing slugs loses dry-run validation
    # of its existing-slug portion too. Correspondence + spec parse already ran at
    # process time, so structural errors still surfaced. (Existing-slug-only
    # assertions carry no ``inline_cites`` and stay on the standard path; real
    # validation of new cites is the snapshot+apply loop.)
    new_inline_cite_ids = {id(p) for p in concrete if p.inline_cites}
    report.asserted += len(new_inline_cite_ids)

    # FK claims on existing entities whose value points at an entity created
    # *in this same plan* cannot be validated in dry-run — the FK existence
    # check queries the DB, but the target is only planned (the live path
    # avoids this because creates run first, in the same transaction).  Same
    # carve-out as deferred relationship claims above: count them asserted,
    # skip validation.  (Structural correctness is already covered.)
    planned = _planned_public_ids(plan.entities)
    fk_to_planned = [
        p for p in concrete if p.handle is None and _fk_value_is_planned(p, planned)
    ]
    report.asserted += len(fk_to_planned)
    fk_to_planned_ids = {id(p) for p in fk_to_planned}

    # Claims targeting existing entities: validate + diff.
    existing_assertions = [
        p
        for p in concrete
        if p.handle is None
        and id(p) not in fk_to_planned_ids
        and id(p) not in new_inline_cite_ids
    ]
    # Entry indexes whose existing-entity claim survives the diff (a real change),
    # for the dry-run empty-diff guard below. Carve-outs are added separately.
    existing_changed: set[EntryIndex] = set()
    if existing_assertions:
        claims = _build_claims(existing_assertions, plan.source)
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
    handle_to_model: dict[str, type[ClaimControlledModel]] = {
        e.handle: e.model_class for e in plan.entities
    }
    # A create whose FK points at *another* same-plan create carries a concrete,
    # handle-targeted provenance claim whose value names the planned target. Its
    # DB existence check would spuriously fail (target only planned), so carve it
    # out exactly like the existing-entity case above. The live path is immune —
    # creates run first in the same transaction, so the target exists by then.
    fk_on_create_planned = [
        p
        for p in concrete
        if p.handle is not None
        and p.handle in handle_to_model
        and _fk_target_is_planned(handle_to_model[p.handle], p, planned)
    ]
    report.asserted += len(fk_on_create_planned)
    fk_on_create_ids = {id(p) for p in fk_on_create_planned}

    planned_assertions = [
        p
        for p in concrete
        if p.handle is not None
        and id(p) not in fk_on_create_ids
        and id(p) not in new_inline_cite_ids
    ]
    if planned_assertions:
        handle_to_ct: dict[str, int] = {
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
                citation=pca.citation,
                source=plan.source,
                needs_review=pca.needs_review,
                needs_review_notes=pca.needs_review_notes,
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
    # new-inline-cite, FK-to-planned) and creates/companions (handle-targeted) —
    # are *assumed* to change; existing-entity assertions count only when their
    # claim survived the diff above. So a plain unchanged-value-with-note entry is
    # rejected at --dry-run too, not only at apply.
    #
    # Skip when validation already collected errors: a rejected (invalid) claim
    # never reaches ``changed``, so the guard would misreport it as a no-op and
    # mask the real validation error. Live is immune — ``_validate_fail_fast``
    # raises before the guard — so this keeps dry-run's diagnostic priority equal.
    if plan.patch_id is not None and not report.errors:
        changed = set(existing_changed)
        for p in plan.assertions:
            assert p.entry_index is not None
            if (
                p.relationship_namespace  # deferred member
                or p.handle is not None  # create or its companion edits
                or p.inline_cites  # new inline citation
                or id(p) in fk_to_planned_ids  # existing FK → same-plan create
            ):
                changed.add(p.entry_index)
        for entry in retract_entries:
            assert entry.entry_index is not None
            changed.add(entry.entry_index)
        _reject_empty_diff_provenance(plan, changed)

    return report


# ---------------------------------------------------------------------------
# Live-path helpers
# ---------------------------------------------------------------------------


def _create_entities(
    entities: list[PlannedEntityCreate],
) -> dict[str, EntityKey]:
    """Bulk-create entities.  Returns ``{handle: EntityKey(ct_id, pk)}``.

    Processes entities in list order, batching consecutive entries of the
    same model class.  Between batches, ``handle_refs`` on upcoming
    entities are resolved from already-created handles so FK dependencies
    across model classes work correctly.

    Handle uniqueness is enforced by ``_validate_assertion_targets``.
    Handle-ref validity is enforced by ``_validate_handle_refs``.
    """
    if not entities:
        return {}

    handle_map: dict[str, EntityKey] = {}

    # Group consecutive entities of the same model class into batches.
    # A batch is flushed when the model class changes OR when an entity's
    # handle_refs reference a handle in the current pending batch (those
    # PKs aren't available until the batch is bulk_created).
    batches: list[list[PlannedEntityCreate]] = []
    current_handles: set[str] = set()
    for entity in entities:
        refs_current_batch = any(
            h in current_handles for h in entity.handle_refs.values()
        )
        if batches and (
            batches[-1][0].model_class is not entity.model_class or refs_current_batch
        ):
            current_handles = set()
            batches.append([entity])
        elif batches:
            batches[-1].append(entity)
        else:
            batches.append([entity])
        current_handles.add(entity.handle)

    for batch in batches:
        model_class = batch[0].model_class
        pairs: list[tuple[PlannedEntityCreate, ClaimControlledModel]] = []
        for entity in batch:
            # Resolve handle_refs into kwargs before instantiation.
            resolved_kwargs = entity.kwargs.copy()
            for kwarg_name, ref_handle in entity.handle_refs.items():
                resolved_kwargs[kwarg_name] = handle_map[ref_handle].object_id
            pairs.append((entity, model_class(**resolved_kwargs)))

        instances = [inst for _, inst in pairs]
        model_class._default_manager.bulk_create(instances)
        ct_id = ContentType.objects.get_for_model(model_class).pk
        for entity, instance in pairs:
            handle_map[entity.handle] = EntityKey(ct_id, instance.pk)

    return handle_map


def _patch_handles(
    assertions: list[PlannedClaimAssert],
    handle_map: dict[str, EntityKey],
) -> None:
    """Resolve temporary handles to real PKs after entity creation.

    Two kinds of handle resolution:

    1. **Target handles** — ``pca.handle`` references the entity this
       claim is *about*.  Patches ``object_id`` and ``content_type_id``.

    2. **Identity refs** — ``pca.identity_refs`` references entities
       whose PKs appear *inside* relationship claim values (e.g. the
       Person PK in a credit claim).  Resolves handles to PKs, merges
       with concrete ``identity``, then calls
       ``build_relationship_claim()`` to generate both ``claim_key``
       and ``value`` in sync.
    """
    from apps.catalog.claims import build_relationship_claim

    for pca in assertions:
        if pca.handle is not None:
            # handle validity already checked by _validate_assertion_targets
            entity_key = handle_map[pca.handle]
            pca.content_type_id = entity_key.content_type_id
            pca.object_id = entity_key.object_id
        if pca.relationship_namespace:
            resolved_identity = dict(pca.identity)
            for key, ref_handle in pca.identity_refs.items():
                resolved_identity[key] = handle_map[ref_handle].object_id
            pca.claim_key, pca.value = build_relationship_claim(
                pca.relationship_namespace, resolved_identity
            )


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
            citation=pca.citation,
            source=source,
            needs_review=pca.needs_review,
            needs_review_notes=pca.needs_review_notes,
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


# ---------------------------------------------------------------------------
# Shared helpers (used by both live and dry-run paths)
# ---------------------------------------------------------------------------


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
            "citation",
            "needs_review",
            "needs_review_notes",
            "license_id",
        ):
            pk, ct, oid, ck, val, cit, nr, nrn, lic_id = row
            existing[ClaimIdentity(ct, oid, ck)] = ExistingClaimRow(
                value=val,
                citation=cit,
                needs_review=nr,
                needs_review_notes=nrn,
                license_id=lic_id,
                pk=pk,
            )

    to_create: list[Claim] = []
    superseded_ids: list[int] = []

    for claim in valid_claims:
        key = ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key)
        old = existing.get(key)
        if old:
            if (
                old.value == claim.value
                and old.citation == claim.citation
                and old.needs_review == claim.needs_review
                and old.needs_review_notes == claim.needs_review_notes
                and old.license_id == claim.license_id
            ):
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


def _collect_plan_provenance(
    plan: IngestPlan,
) -> tuple[EntryNotes, ClaimCitations, ClaimEntryIndex]:
    """Gather per-entry ``note``/``citation_ref`` and the claim→entry grouping map.

    Source-agnostic — any plan may set these; today only the patch adapter does
    (from a patch entry's ``note:``/``cite:``). Runs after ``_patch_handles``,
    so every assertion's ct/obj is resolved. Returns three maps:

    * ``entry_notes`` (keyed by the authoring entry's ``entry_index``) feeds each
      per-entry ChangeSet's note.
    * ``claim_citations`` (keyed by the exact claim identity) drives per-claim
      citation attachment in ``_attach_plan_citations``. Keyed per claim — never
      per entry — so a citation never bleeds onto unrelated claims (or the
      create-owned scaffolding) that merely share the entity.
    * ``claim_entry_index`` (keyed by claim identity) lets ``_persist`` group
      built claims into per-entry ChangeSets. Recorded for *every* patch
      assertion — note-less ones included — so a multi-entry patch still groups
      correctly. Skipped when ``entry_index`` is ``None`` (non-patch runs), which
      keeps the value type a clean ``int``; ``_persist`` reads it only in patch
      mode, where the coupling check has proven every index non-``None``.

    The disjoint-field guard ensures no two entries assert the same
    ``ClaimIdentity``, so the map is 1:1 with the deduped claim set and
    last-write-wins on a note/citation here is never reached in practice.
    """
    entry_notes: EntryNotes = {}
    claim_citations: ClaimCitations = {}
    claim_entry_index: ClaimEntryIndex = {}
    for pca in plan.assertions:
        ct_id = pca.content_type_id
        obj_id = pca.object_id
        # post _patch_handles: handles are resolved to real ct/obj.
        assert ct_id is not None
        assert obj_id is not None
        ident = ClaimIdentity(ct_id, obj_id, pca.claim_key or pca.field_name)
        if pca.entry_index is not None:
            claim_entry_index[ident] = pca.entry_index
        if not pca.note and pca.citation_ref is None:
            continue  # the common case (all normal-ingest assertions)
        if pca.note:
            # A note only ever rides a patch entry, which always stamps its index.
            assert pca.entry_index is not None
            entry_notes[pca.entry_index] = pca.note
        if pca.citation_ref is not None:
            claim_citations[ident] = pca.citation_ref
    for pcr in plan.retractions:
        if pcr.note:
            assert pcr.entry_index is not None
            entry_notes[pcr.entry_index] = pcr.note
    return entry_notes, claim_citations, claim_entry_index


def _check_empty_diff_entries(
    plan: IngestPlan,
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
    claim_entry_index: ClaimEntryIndex,
) -> None:
    """Live-path empty-diff guard: surviving claims/retractions are the change.

    Maps each surviving built claim back to its authoring entry via
    ``claim_entry_index`` and delegates to :func:`_reject_empty_diff_provenance`.
    The dry-run path computes ``changed`` differently (see ``_apply_dry_run``); the
    rejection logic itself is shared.
    """
    if plan.patch_id is None:
        return

    changed: set[EntryIndex] = set()
    for claim in to_create:
        changed.add(
            claim_entry_index[
                ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key)
            ]
        )
    for entry in retract_entries:
        assert entry.entry_index is not None
        changed.add(entry.entry_index)

    _reject_empty_diff_provenance(plan, changed)


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
    into apply.py.

    Patch-only (``patch_id`` set); non-patch runs carry no per-entry provenance.
    Raises ``ValidationError`` (apply.py is source-agnostic and must not import
    ``PatchError``); ``_apply_one`` converts it to a clean ``PatchError``.
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


def _resolve_cite_source_id(ref: CitationRef, cache: dict[CitationRef, int]) -> int:
    """Resolve a ``CitationRef`` to a ``CitationSource`` pk, memoized via ``cache``.

    Shared by the field-level ``cite:`` path (:func:`_attach_plan_citations`) and
    the inline-footnote path (:func:`_materialize_inline_citations`). Uses the
    same ``get_or_create_*`` resolvers, so source dedup, web-root matching and
    ``{url, archive}`` backfill come free. Created sources are *uncounted* — the
    resolvers return a bare ``CitationSource``, not created-ness — matching the
    field-``cite:`` stance (only the ``sources:`` block bumps the counters).
    """
    source_id = cache.get(ref)
    if source_id is None:
        from apps.citation.extractors import (
            get_or_create_external_source,
            get_or_create_web_source,
        )

        if ref.url:
            source_id = get_or_create_web_source(ref.url, ref.archive_url).pk
        else:
            source_id = get_or_create_external_source(ref.scheme, ref.identifier).pk
        cache[ref] = source_id
    return source_id


def _attach_plan_citations(
    to_create: list[Claim],
    claim_citations: ClaimCitations,
) -> None:
    """Materialize per-claim ``CitationRef``s as ``CitationInstance`` rows.

    Runs after ``_persist`` so created claims have PKs. A citation only rides
    a *newly written* claim: a value that diffs as unchanged produces no
    ``to_create`` entry, so re-asserting an already-correct value purely to
    add a ``cite:`` is a documented no-op (see docs/DataPatches.md).
    """
    if not claim_citations:
        return
    from apps.provenance.models import CitationInstance

    source_cache: dict[CitationRef, int] = {}
    instances: list[CitationInstance] = []
    for claim in to_create:
        ref = claim_citations.get(
            ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key)
        )
        if ref is None:
            continue
        source_id = _resolve_cite_source_id(ref, source_cache)
        instances.append(CitationInstance(citation_source_id=source_id, claim=claim))
    if instances:
        CitationInstance.objects.mint_many(instances)


def _materialize_inline_citations(assertions: list[PlannedClaimAssert]) -> None:
    """Mint floating ``CitationInstance`` rows for *new* inline citations.

    For each assertion carrying ``inline_cites`` (a ``{numeric-handle:
    CitationRef}`` map populated by the patch adapter), mints one
    ``claim=None`` ``CitationInstance`` per handle, then rewrites that handle's
    ``[[cite:<handle>]]`` markers in the assertion value to the minted
    ``[[cite:<slug>]]``. Existing-slug markers are left untouched.

    Runs after ``_patch_handles`` (so a same-patch ``create:``'s handle-targeted
    assertion already carries real ct/obj — created and edited entities handled
    identically) and *before* ``_build_claims``/validation, so the standard
    ``convert_authoring_to_storage`` then resolves every ``[[cite:slug]]`` to
    ``[[cite:id:pk]]`` storage and ``_diff_claims`` diffs the final text — no
    bespoke storage rewrite here. Live path only: dry-run never reaches here (it
    carves new-cite assertions out before minting). Inside ``apply_plan``'s
    ``transaction.atomic()``, so a failed apply rolls the mint back; ``mint_many``
    is savepoint-wrapped for slug-collision retry.
    """
    cited = [pca for pca in assertions if pca.inline_cites]
    if not cited:
        return
    from apps.provenance.models import CitationInstance

    # Mint every new instance in one batch, tracking the (assertion, handle) each
    # belongs to so we can read its assigned slug back after mint_many. Minting is
    # per-assertion (i.e. per markdown field): a handle reused across two markdown
    # fields of one entry would mint one instance per field — the design's
    # per-field footnote semantics, not a shared one. Moot while every entity has
    # a single markdown field; intentional if that ever changes.
    source_cache: dict[CitationRef, int] = {}
    instances: list[CitationInstance] = []
    owners: list[tuple[PlannedClaimAssert, CiteHandle]] = []
    for pca in cited:
        for handle, ref in pca.inline_cites.items():
            source_id = _resolve_cite_source_id(ref, source_cache)
            instances.append(CitationInstance(citation_source_id=source_id, claim=None))
            owners.append((pca, handle))
    CitationInstance.objects.mint_many(instances)  # assigns each ``.slug`` in place

    for (pca, handle), instance in zip(owners, instances, strict=True):
        # Full-marker literal replace: the closing ``]]`` makes ``[[cite:1]]``
        # unambiguous against ``[[cite:11]]``, so no regex/order hazard.
        assert isinstance(pca.value, str)
        pca.value = pca.value.replace(f"[[cite:{handle}]]", f"[[cite:{instance.slug}]]")


def _persist(
    run: IngestRun,
    to_create: list[Claim],
    superseded_ids: list[int],
    retract_entries: list[RetractEntry],
    entry_notes: EntryNotes,
    claim_entry_index: ClaimEntryIndex,
) -> None:
    """Bulk-create ChangeSets and Claims, deactivate superseded/retracted.

    Superseded claims are deactivated *before* new claims are inserted to satisfy
    the partial unique index on ``(content_type, object_id, source, claim_key)``
    where ``is_active=True``. ``superseded_ids`` is always a subset of the
    entities in ``to_create`` (a superseded claim has a replacement), so the
    empty-check on ``to_create`` is sufficient.

    Grouping is mode-selected on ``run.patch_id``: patch runs mint one ChangeSet
    per authoring entry (``entry_index``, carrying that entry's note); normal
    ingests (IPDB/OPDB) mint one per affected entity. A run is single-adapter, so
    exactly one mode is in force.
    """
    if not to_create and not retract_entries:
        return

    if superseded_ids:
        Claim.objects.filter(pk__in=superseded_ids).update(is_active=False)

    if run.patch_id is not None:
        _persist_per_entry(
            run, to_create, retract_entries, entry_notes, claim_entry_index
        )
    else:
        _persist_per_entity(run, to_create, retract_entries)


def _link_to_changesets[K](
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
    group_to_cs: dict[K, ChangeSet],
    claim_group: Callable[[Claim], K],
    retract_group: Callable[[RetractEntry], K],
) -> None:
    """Point each new claim and retraction at its ChangeSet, then write.

    Shared tail of the two ``_persist_*`` modes — they differ only in the grouping
    key (``entry_index`` vs ``EntityKey``), supplied here as the ``claim_group`` /
    ``retract_group`` extractors over an already-built ``group_to_cs``. Retracted
    claims are deactivated in bulk per ChangeSet, stamped ``retracted_by_changeset``.
    """
    for claim in to_create:
        claim.changeset_id = group_to_cs[claim_group(claim)].pk
    if to_create:
        Claim.objects.bulk_create(to_create, batch_size=2000)

    if retract_entries:
        retract_by_cs: dict[int, list[int]] = defaultdict(list)
        for entry in retract_entries:
            retract_by_cs[group_to_cs[retract_group(entry)].pk].append(entry.pk)
        for cs_pk, pks in retract_by_cs.items():
            Claim.objects.filter(pk__in=pks).update(
                is_active=False,
                retracted_by_changeset_id=cs_pk,
            )


def _persist_per_entry(
    run: IngestRun,
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
    entry_notes: EntryNotes,
    claim_entry_index: ClaimEntryIndex,
) -> None:
    """One ChangeSet per authoring patch entry, grouped by ``entry_index``.

    Entry indexes are sorted ascending before ``bulk_create`` so ChangeSet pk
    order matches file order — load-bearing because every ChangeSet in one
    ``bulk_create`` shares ``created_at`` (db_default ``Now()``), leaving pk as
    history's only file-order tiebreak (see ``history.py``: ``-created_at, -pk``).
    A cascade-delete entry stamps one index across several entities, so its whole
    cascade lands in a single multi-entity ChangeSet — matching the in-app delete.
    """

    def claim_idx(claim: Claim) -> EntryIndex:
        return claim_entry_index[
            ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key)
        ]

    def retract_idx(entry: RetractEntry) -> EntryIndex:
        assert entry.entry_index is not None  # patch retractions are always stamped
        return entry.entry_index

    ordered = sorted(
        {claim_idx(c) for c in to_create} | {retract_idx(e) for e in retract_entries}
    )
    changesets = [
        ChangeSet(ingest_run=run, note=entry_notes.get(idx, "")) for idx in ordered
    ]
    ChangeSet.objects.bulk_create(changesets)
    idx_to_cs = dict(zip(ordered, changesets, strict=True))
    _link_to_changesets(to_create, retract_entries, idx_to_cs, claim_idx, retract_idx)


def _persist_per_entity(
    run: IngestRun,
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
) -> None:
    """One ChangeSet per affected entity — the normal-ingest (IPDB/OPDB) path.

    Non-patch runs carry no per-entry notes, so each ChangeSet's note is empty.
    """

    def claim_entity(claim: Claim) -> EntityKey:
        return EntityKey(claim.content_type_id, claim.object_id)

    def retract_entity(entry: RetractEntry) -> EntityKey:
        return EntityKey(entry.content_type_id, entry.object_id)

    ordered = sorted(
        {claim_entity(c) for c in to_create}
        | {retract_entity(e) for e in retract_entries}
    )
    changesets = [ChangeSet(ingest_run=run, note="") for _ in ordered]
    ChangeSet.objects.bulk_create(changesets)
    entity_to_cs = dict(zip(ordered, changesets, strict=True))
    _link_to_changesets(
        to_create, retract_entries, entity_to_cs, claim_entity, retract_entity
    )


def _resolve(
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
    resolve_hooks: dict[int, list[ResolveHook]],
) -> None:
    """Materialise resolved values on affected entities."""
    from apps.catalog.resolve._entities import resolve_all_entities

    affected_by_ct: dict[int, set[int]] = defaultdict(set)
    for claim in to_create:
        affected_by_ct[claim.content_type_id].add(claim.object_id)
    for entry in retract_entries:
        affected_by_ct[entry.content_type_id].add(entry.object_id)

    for ct_id, obj_ids in affected_by_ct.items():
        model_class = ContentType.objects.get_for_id(ct_id).model_class()
        if model_class is None:
            continue
        # Affected CTs are always claim-controlled catalog entities by
        # construction (they carry claims).  ContentType.model_class()
        # returns ``type[Model]``, so the narrowing cast is unavoidable.
        resolve_all_entities(
            cast(type[ClaimControlledModel], model_class), object_ids=obj_ids
        )
        for hook in resolve_hooks.get(ct_id, []):
            hook(subject_ids=obj_ids)
