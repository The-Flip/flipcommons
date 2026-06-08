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
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol, cast

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models, transaction
from django.utils import timezone

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


class ResolveHook(Protocol):
    """Signature for relationship resolvers registered in ``resolve_hooks``.

    Matches the standardised resolve function signature::

        def resolve_all_gameplay_features(*, subject_ids: set[int] | None = None) -> None
    """

    def __call__(self, *, subject_ids: set[int] | None = None) -> None: ...


class RetractEntry(NamedTuple):
    """An active claim targeted for retraction."""

    pk: int
    content_type_id: int
    object_id: int


# ---------------------------------------------------------------------------
# Plan data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CitationRef:
    """A parsed, normalized reference to an external citation source.

    ``scheme`` is an ``apps.citation.extractors.EXTRACTORS`` key (e.g.
    ``"ipdb"``); ``identifier`` is the normalized in-scheme id (e.g.
    ``"4443"``). Resolved to a ``CitationSource`` at apply time via
    ``get_or_create_external_source`` — no DB access to construct one.

    Defined here, beside the plan dataclasses, rather than in any source
    adapter: the source-agnostic apply layer must not import an adapter, and
    adapters (e.g. ``ingestion.patches``) already import the plan carriers
    from this module.
    """

    scheme: str
    identifier: str


# Per-claim provenance maps produced by ``_collect_plan_provenance`` and
# consumed by ``_persist`` / ``_attach_plan_citations``. Named so the opaque
# ``str`` (a ChangeSet note) and the per-claim citation mapping read clearly
# wherever they recur.
type EntityNotes = dict[EntityKey, str]
type ClaimCitations = dict[ClaimIdentity, CitationRef]


@dataclass
class PlannedEntityCreate:
    """A new catalog entity to be created inside the apply transaction.

    ``handle`` is a temporary identifier used by ``PlannedClaimAssert``
    to reference this entity before it has a PK.  Handles must be unique
    within a plan.

    ``handle_refs`` maps kwarg names to handles of other planned entities.
    After the referenced entity is created, the framework patches the
    kwarg to the created entity's PK.  This solves cross-entity FK
    dependencies (e.g. CorporateEntity needs ``manufacturer_id`` from a
    planned Manufacturer).  Entities must appear in the list **after**
    anything they reference — the adapter controls ordering.
    """

    model_class: type[ClaimControlledModel]
    # kwargs are spread into ``model_class(**kwargs)`` — schema varies per
    # model class, so the value type is genuinely heterogeneous.
    kwargs: dict[str, Any]
    handle: str
    handle_refs: dict[str, str] = field(default_factory=dict)


@dataclass
class PlannedClaimAssert:
    """A claim to assert about a catalog entity.

    Must target exactly one of:
    - An existing entity: set ``content_type_id`` and ``object_id``.
    - A planned entity: set ``handle`` (matching a ``PlannedEntityCreate``).

    Relationship claim identity uses exactly one of:
    - ``claim_key`` + ``value`` — fully concrete (adapter calls
      ``build_relationship_claim()`` itself).
    - ``relationship_namespace`` + ``identity`` + ``identity_refs`` —
      deferred.  The apply layer resolves handles in ``identity_refs``
      to real PKs, then calls ``build_relationship_claim()`` to generate
      both ``claim_key`` and ``value`` in sync.  This avoids the two
      getting out of sync when relationship identity includes entities
      created in the same plan.
    """

    field_name: str
    # ``value`` is the raw JSONField payload — scalar, dict, list, or null;
    # genuinely arbitrary, so the type stays open.
    value: Any = None
    claim_key: str = ""
    # Legacy free-text citation string written to ``Claim.citation`` (used by
    # some ingest paths). Distinct from ``citation_ref`` below, which is the
    # structured CitationInstance reference — don't conflate them.
    citation: str = ""
    # Per-entry patch provenance. ``note`` flows to the entity's ChangeSet
    # note; ``citation_ref`` (set only on explicit-field assertions, never the
    # create-owned slug/status scaffolding) is materialized as a
    # CitationInstance on the resulting claim at apply time.
    note: str = ""
    citation_ref: CitationRef | None = None
    content_type_id: int | None = None
    object_id: int | None = None
    handle: str | None = None
    needs_review: bool = False
    needs_review_notes: str = ""
    license_id: int | None = None
    # Deferred relationship claim identity:
    relationship_namespace: str = ""
    # identity values mix PKs (int) and tag values (str/bool) per the
    # relationship's claim-key schema; truly heterogeneous.
    identity: dict[str, Any] = field(default_factory=dict)
    identity_refs: dict[str, str] = field(default_factory=dict)


@dataclass
class PlannedClaimRetract:
    """An explicit retraction of a previously-active claim."""

    content_type_id: int
    object_id: int
    claim_key: str
    # Per-entry patch note → the entity's ChangeSet note. A retraction has no
    # new claim, so it carries no ``citation_ref``.
    note: str = ""


@dataclass
class IngestPlan:
    """Declarative description of everything a source wants to write."""

    source: Source
    input_fingerprint: str
    entities: list[PlannedEntityCreate] = field(default_factory=list)
    assertions: list[PlannedClaimAssert] = field(default_factory=list)
    retractions: list[PlannedClaimRetract] = field(default_factory=list)
    records_parsed: int = 0
    records_matched: int = 0
    resolve_hooks: dict[int, list[ResolveHook]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Patch runs only: the NNNN-slug filename stem (the applied-ledger key)
    # and the patch's description (copied to ``IngestRun.note``). Null/empty
    # for normal ingests.
    patch_id: str | None = None
    note: str = ""


@dataclass
class RunReport:
    """Counts and diagnostics returned by ``apply_plan``."""

    records_created: int = 0
    asserted: int = 0
    unchanged: int = 0
    superseded: int = 0
    retracted: int = 0
    rejected: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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
            handle_map = _create_entities(plan.entities)
            report.records_created = len(plan.entities)

            _patch_handles(plan.assertions, handle_map)
            # Per-claim provenance (note/citation) carried by the plan, collected
            # once now that handles are resolved (so every assertion carries its
            # real ct/obj). Kept out of _build_claims so that helper's signature —
            # and its dry-run call site — stay untouched.
            entity_notes, claim_citations = _collect_plan_provenance(plan)
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

            _persist(run, to_create, superseded_ids, retract_entries, entity_notes)
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


def _fk_value_is_planned(
    pca: PlannedClaimAssert,
    planned: dict[type[ClaimControlledModel], set[str]],
) -> bool:
    """True if *pca* is an FK claim whose value names a same-plan-created entity.

    *planned* is the precomputed ``_planned_public_ids`` map. Used only by the
    dry-run path to skip DB existence validation for FK targets that don't
    exist yet because they're created in this same plan.
    """
    if pca.content_type_id is None or not isinstance(pca.value, str):
        return False
    model_class = ContentType.objects.get_for_id(pca.content_type_id).model_class()
    if model_class is None:
        return False
    try:
        django_field = model_class._meta.get_field(pca.field_name)
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
        p for p in concrete if p.handle is None and id(p) not in fk_to_planned_ids
    ]
    if existing_assertions:
        claims = _build_claims(existing_assertions, plan.source)
        valid = _validate_and_collect_errors(claims, report)
        if valid:
            to_create, superseded_ids = _diff_claims(valid, plan.source)
            report.asserted += len(to_create)
            report.unchanged += len(valid) - len(to_create)
            report.superseded += len(superseded_ids)

    # Claims targeting planned entities: validate only (all are new by
    # definition).  Build sentinel claims without mutating the plan.
    planned_assertions = [p for p in concrete if p.handle is not None]
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
    if plan.retractions:
        entries = _process_retractions(plan.retractions, plan.source, report)
        report.retracted = len(entries)

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
                RetractEntry(found_pk, key.content_type_id, key.object_id)
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
) -> tuple[EntityNotes, ClaimCitations]:
    """Gather per-claim ``note``/``citation_ref`` carried by the plan into maps.

    Source-agnostic — any plan may set these; today only the patch adapter does
    (from a patch entry's ``note:``/``cite:``). Runs after ``_patch_handles``,
    so every assertion's ct/obj is resolved. ``entity_notes`` (keyed by entity)
    feeds the per-entity ChangeSet note; ``claim_citations`` (keyed by the exact
    claim identity) drives per-claim citation attachment in
    ``_attach_plan_citations``. Citations are keyed per claim — never per
    entity — so a citation never bleeds onto unrelated claims (or the
    create-owned scaffolding) that merely share the entity.

    The patch adapter's same-entity guard ensures no two entries put conflicting
    notes on one entity, so last-write-wins here is never reached in practice.
    """
    entity_notes: EntityNotes = {}
    claim_citations: ClaimCitations = {}
    for pca in plan.assertions:
        if not pca.note and pca.citation_ref is None:
            continue  # the common case (all normal-ingest assertions)
        ct_id = pca.content_type_id
        obj_id = pca.object_id
        # post _patch_handles: handles are resolved to real ct/obj.
        assert ct_id is not None
        assert obj_id is not None
        if pca.note:
            entity_notes[EntityKey(ct_id, obj_id)] = pca.note
        if pca.citation_ref is not None:
            claim_citations[
                ClaimIdentity(ct_id, obj_id, pca.claim_key or pca.field_name)
            ] = pca.citation_ref
    for pcr in plan.retractions:
        if pcr.note:
            entity_notes[EntityKey(pcr.content_type_id, pcr.object_id)] = pcr.note
    return entity_notes, claim_citations


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
    from apps.citation.extractors import get_or_create_external_source
    from apps.provenance.models import CitationInstance

    source_cache: dict[CitationRef, int] = {}
    instances: list[CitationInstance] = []
    for claim in to_create:
        ref = claim_citations.get(
            ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key)
        )
        if ref is None:
            continue
        source_id = source_cache.get(ref)
        if source_id is None:
            source_id = get_or_create_external_source(ref.scheme, ref.identifier).pk
            source_cache[ref] = source_id
        instances.append(CitationInstance(citation_source_id=source_id, claim=claim))
    if instances:
        CitationInstance.objects.bulk_create(instances)


def _persist(
    run: IngestRun,
    to_create: list[Claim],
    superseded_ids: list[int],
    retract_entries: list[RetractEntry],
    entity_notes: EntityNotes,
) -> None:
    """Bulk-create ChangeSets and Claims, deactivate superseded/retracted.

    Superseded claims are deactivated *before* new claims are inserted
    to satisfy the unique constraint on
    ``(content_type, object_id, source, claim_key)`` where
    ``is_active=True``.

    ``entity_notes`` carries each affected entity's patch ``note:`` onto its
    ChangeSet (empty string when the entry set none).
    """
    # superseded_ids is always a subset of the entities in to_create (a
    # superseded claim has a replacement in to_create), so checking
    # to_create is sufficient.
    if not to_create and not retract_entries:
        return

    # One ChangeSet per affected entity.
    affected: set[EntityKey] = set()
    for claim in to_create:
        affected.add(EntityKey(claim.content_type_id, claim.object_id))
    for entry in retract_entries:
        affected.add(EntityKey(entry.content_type_id, entry.object_id))

    entity_list = sorted(affected)
    changesets = [
        ChangeSet(ingest_run=run, note=entity_notes.get(ek, "")) for ek in entity_list
    ]
    ChangeSet.objects.bulk_create(changesets)
    entity_to_cs: dict[EntityKey, ChangeSet] = dict(
        zip(entity_list, changesets, strict=True),
    )

    # Deactivate superseded claims before inserting replacements.
    if superseded_ids:
        Claim.objects.filter(pk__in=superseded_ids).update(is_active=False)

    # Assign changeset and bulk-create new claims.
    for claim in to_create:
        claim.changeset_id = entity_to_cs[
            EntityKey(claim.content_type_id, claim.object_id)
        ].pk

    if to_create:
        Claim.objects.bulk_create(to_create, batch_size=2000)

    # Deactivate retracted claims with changeset link.
    if retract_entries:
        retract_by_cs: dict[int, list[int]] = defaultdict(list)
        for entry in retract_entries:
            cs = entity_to_cs[EntityKey(entry.content_type_id, entry.object_id)]
            retract_by_cs[cs.pk].append(entry.pk)

        for cs_pk, pks in retract_by_cs.items():
            Claim.objects.filter(pk__in=pks).update(
                is_active=False,
                retracted_by_changeset_id=cs_pk,
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
