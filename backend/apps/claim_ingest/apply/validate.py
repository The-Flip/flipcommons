"""Structural plan validation — leaf module, run before the live/dry-run split.

Cheap, DB-light integrity checks over an :class:`IngestPlan`'s shape: handle
uniqueness and ordering, entity↔claim consistency, assertion targeting, patch
entry-index stamping. These raise plain ``ValueError`` — they catch *adapter*
bugs (a malformed plan), not source-data problems, so they fire before any
``IngestRun`` is created and leave no audit debris.

Both the live (:mod:`.orchestrate`) and dry-run (:mod:`.dry_run`) paths run
these, so they live in their own leaf with no intra-package dependencies.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import models

from apps.claim_ingest.plan import Handle, IngestPlan


def _validate_entity_claim_consistency(plan: IngestPlan) -> None:
    """Every claim-controlled field populated by a PlannedEntityCreate
    (via kwargs or handle_refs) must have a matching PlannedClaimAssert
    targeting the same handle."""
    from apps.provenance.models import get_claim_fields

    asserted_by_handle: dict[Handle, set[str]] = defaultdict(set)
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
    seen: set[Handle] = set()
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
    """Every assertion/retraction must carry an ``entry_index``.

    ``_persist`` groups ChangeSets by ``entry_index``, so a missed stamp would
    silently collapse the whole run under a single group. The front end stamps
    every entry in a second pass (see ``planning.build_plan``); this guards that
    invariant — a plain ``ValueError`` (an internal bug), not a source-facing
    ``ValidationError``/``PatchError``.
    """
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
        seen: set[Handle] = set()
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
