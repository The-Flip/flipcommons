"""Dry-run path: validate and diff a plan without writing anything.

:func:`_apply_dry_run` mirrors the live path's compute steps (build → validate →
diff, via :mod:`.claims`) but commits nothing and reports validation failures
non-fatally. Its bulk is carve-outs: assertions the live path validates only
because creates run first in the same transaction — deferred relationship
claims, FK targets pointing at same-plan creates, new inline citations — can't be
DB-validated here, so they're counted as asserted and skipped. The
:func:`_planned_public_ids` / ``_fk_*_is_planned`` helpers identify those FK
carve-outs.

Depends on :mod:`.claims` for the shared build/validate/diff helpers; structural
validation already ran in :mod:`.orchestrate` before the fork. Deliberately does
**not** touch :mod:`.persist` — the dry-run path never writes.
"""

from __future__ import annotations

from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from apps.catalog.ingestion.apply.claims import (
    RetractEntry,
    _build_claims,
    _diff_claims,
    _process_retractions,
    _reject_empty_diff_provenance,
    _validate_and_collect_errors,
)
from apps.catalog.ingestion.plan import (
    EntryIndex,
    Handle,
    IngestPlan,
    PlannedClaimAssert,
    PlannedEntityCreate,
    RunReport,
)
from apps.core.types import ClaimIdentity
from apps.provenance.models import Claim, ClaimControlledModel


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
    handle_to_model: dict[Handle, type[ClaimControlledModel]] = {
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
                source=plan.source,
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
