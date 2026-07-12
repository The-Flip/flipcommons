"""Orchestration layer: :class:`PatchDoc` → :class:`IngestPlan` (``build_plan``).

The top of the package — imported by no sibling module. ``build_plan`` runs a
two-phase compile: ``_process_entry`` resolves each entry against the DB and
calls into :mod:`.emit` to append its plan rows, then ``_validate_plan_wide``
runs the cross-entry guards (per-record ChangeSet disjointness, hierarchy
acyclicity, provenance-carrier presence) over the collected ``_EntryResult``\\ s.
Consumes :mod:`.parsing`, drives :mod:`.emit`, shares carriers from
:mod:`._types`. Entry point: :func:`build_plan`.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from collections.abc import Set as AbstractSet
from typing import NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.actors.models import Actor
from apps.citation.source_node import SourceNode
from apps.citation.source_upsert import (
    detect_host_collision,
    ensure_root_source,
    validate_root_source,
)
from apps.claim_ingest.patches._types import (
    PatchError,
    _CreatedKey,
    _Target,
)
from apps.claim_ingest.patches.emit import (
    RelFieldsByModel,
    _add_create,
    _add_delete,
    _add_removals,
    _add_retractions,
    _emit_direct,
    _emit_relationship,
    _HierarchyEdge,
    _resolve_model_class,
)
from apps.claim_ingest.patches.entity_registry import PatchEntityRegistry
from apps.claim_ingest.patches.parsing import (
    _CITE_MARKER_RE,
    _NUMERIC_HANDLE_RE,
    _SLUG_HANDLE_RE,
    CreateEntry,
    DeleteEntry,
    EditEntry,
    PatchDoc,
    PatchEntry,
    _parse_provenance,
)
from apps.claim_ingest.plan import (
    CiteHandle,
    CiteSpec,
    DryRunPreviewHook,
    Handle,
    IngestPlan,
    Namespace,
    PreWriteHook,
    RunReport,
)
from apps.core.markdown import get_markdown_fields
from apps.core.models import (
    LIFECYCLE_STATUS_FIELD,
    LifecycleStatusModel,
    LinkableModel,
)
from apps.core.soft_delete import cascade_targets, require_linkable
from apps.core.types import ClaimKey, EntityKey, PublicId
from apps.provenance.claims import normalize_fk_value
from apps.provenance.models import LinkableClaimModel, Source, get_claim_fields
from apps.provenance.validation import get_relationship_namespaces

# A plan-wide guard target: an existing entity (``EntityKey``) or a same-patch
# create addressed by its ``Handle``. The two never collide — a 2-int
# ``NamedTuple`` vs a handle string — so they share one accumulator keyspace.
type _TargetKey = EntityKey | Handle


class _TargetContribution(NamedTuple):
    """One entry's contribution to the plan-wide guards for one target.

    The target is an existing entity (keyed by ``EntityKey``) or a same-patch
    create (keyed by its ``Handle``). A create contributes its authored +
    identity (slug) claims under its handle, so the disjoint-claims guard spans
    the create and any companion edits that refine it; a delete contributes one
    of these per soft-deleted entity (root + cascade) with empty field sets and
    ``from_delete=True``; an edit contributes one carrying its retract / assert /
    remove sets. ``_validate_plan_wide`` merges these across entries, enforcing
    per-entry-ChangeSet disjointness.

    ``deferred_member_ids`` are ``"namespace <composite>"`` keys for members with
    at least one slot pointing at a same-patch create — the composite is a pk or
    handle per identity slot. Kept apart from ``asserted_members`` (concrete
    claim_keys) because their real claim_key isn't known until apply time, but
    still guarded for cross-entry duplication.
    """

    ref: str
    from_delete: bool
    retracted_fields: frozenset[str]
    asserted_fields: frozenset[str]
    asserted_members: frozenset[ClaimKey]
    deferred_member_ids: frozenset[str]
    # claim_key → "namespace public_id" label, for the assert/remove clash error.
    removed_members: dict[ClaimKey, str]


class _EntryResult(NamedTuple):
    """What ``_process_entry`` hands back for the cross-entry validation passes.

    The plan mutations (entities, assertions, retractions, warnings) have already
    happened inside ``_process_entry``; this carries only what the plan-wide
    guards need. ``matched`` counts toward ``records_matched`` (edit/delete yes,
    create no). ``hierarchy_edges`` are this entry's self-referential child→parent
    edges, aggregated across entries for the plan-wide acyclicity guard.
    """

    matched: bool
    contributions: dict[_TargetKey, _TargetContribution]
    hierarchy_edges: list[_HierarchyEdge]


def build_plan(doc: PatchDoc, *, source: Source, patch_id: str) -> IngestPlan:
    """Compile a parsed patch into an :class:`IngestPlan`.

    Drives the two-phase compile: ``_process_entry`` resolves, validates and
    emits each entry (all DB reads + plan mutations happen there, in order),
    returning an :class:`_EntryResult`; ``_validate_plan_wide`` then runs the
    cross-entry guards over the collected results. ``apply_plan(plan)`` does the
    writing.
    """
    plan = IngestPlan(
        source=source,
        input_fingerprint=doc.fingerprint,
        patch_id=patch_id,
        note=doc.description,
        records_parsed=len(doc.claims),
    )
    rel_namespaces = get_relationship_namespaces()
    rel_fields_by_model: RelFieldsByModel = defaultdict(set)
    # The patch's symbol table: what entity each reference names — a committed
    # entity, a same-patch create, or neither. Replaces the three reference-
    # resolution paths the front end used to thread separately (a create→handle
    # map, a create-ref dedup set and an inline live-DB lookup).
    registry = PatchEntityRegistry()
    # Identity of every create in the patch, regardless of file order — a cheap
    # pre-scan so an edit that resolves nowhere can tell *create-appears-below*
    # from *no-such-record*. The registry's single-pass create map only holds
    # creates seen so far, so it can't distinguish the two on its own. A create
    # whose entity_type doesn't resolve is skipped here and errors when that entry
    # is processed, preserving per-entry error attribution.
    all_created_ids: set[_CreatedKey] = set()
    for candidate in doc.claims:
        if isinstance(candidate, CreateEntry):
            with contextlib.suppress(PatchError):
                all_created_ids.add(
                    _CreatedKey(_resolve_model_class(candidate), candidate.public_id)
                )
    # Reject reassigning an FK onto an entity this patch deletes — a dangling
    # reference the committed delete-blocker can't see. A build-time set
    # intersection over the patch's FK targets and its delete footprint; no
    # resolver, no divergence.
    _reject_reassign_onto_delete(doc, registry)
    # Stamp each entry's emissions with its file-order index for per-entry
    # ChangeSet grouping (apply layer). An entry's assertions/retractions are all
    # appended during its own ``_process_entry`` call and land contiguously at the
    # end of the plan lists (single-pass, nothing else appends between entries),
    # so slice-stamping the tail after each call is exact — and avoids threading
    # ``entry_index`` through every ``_emit_*``/``_add_*`` helper.
    results: list[_EntryResult] = []
    for entry_index, entry in enumerate(doc.claims):
        assert_start = len(plan.assertions)
        retract_start = len(plan.retractions)
        results.append(
            _process_entry(
                plan,
                entry,
                source=source,
                rel_namespaces=rel_namespaces,
                rel_fields_by_model=rel_fields_by_model,
                registry=registry,
                all_created_ids=all_created_ids,
            )
        )
        for pca in plan.assertions[assert_start:]:
            pca.entry_index = entry_index
        for pcr in plan.retractions[retract_start:]:
            pcr.entry_index = entry_index
    plan.records_matched = sum(r.matched for r in results)
    _validate_plan_wide(results)
    # Acyclicity guard over every entry's self-referential child→parent edges.
    hierarchy_edges = [edge for r in results for edge in r.hierarchy_edges]
    _validate_hierarchy_acyclic(hierarchy_edges)

    # Relationship resolution: record which relationship namespaces each
    # affected content type touched, as plan data. The apply engine's
    # ``_resolve`` dispatches them to the provenance bulk resolver (which
    # resolves scalar/FK regardless; this set scopes the relationship pass).
    for rel_model, field_names in rel_fields_by_model.items():
        rel_ct_id = ContentType.objects.get_for_model(rel_model).pk
        existing = plan.changed_relationship_fields.get(rel_ct_id, frozenset())
        plan.changed_relationship_fields[rel_ct_id] = existing | frozenset(field_names)

    _plan_citation_sources(plan, doc.sources)

    return plan


def _reject_reassign_onto_delete(doc: PatchDoc, registry: PatchEntityRegistry) -> None:
    """Reject a patch whose FK claim targets an entity the same patch deletes.

    Reassigning a live reference *onto* an entity this patch soft-deletes leaves a
    dangling reference: post-apply, a live row points at a soft-deleted entity.
    The committed delete-blocker (``plan_soft_delete``) can't catch it — it
    enumerates rows that point at the target *now*, but a row this patch reassigns
    onto the target doesn't point there yet, so it's absent from the enumeration.
    This build-time guard closes the hole by construction, at the FK-claim level —
    no resolver, so it adds no predict-vs-actual divergence.

    The guard is **syntactic**: it fires on the FK claim *target*, not the
    resolved post-patch FK. So it also rejects a few coherent-but-pointless shapes
    (an FK claim that loses resolution; a referrer itself deleted in the same
    patch). All are the one contradiction — point-at-X and delete-X in one file —
    and rejecting them is the strict, defensible choice.

    Covers FK claims on **both creates and edits** — its own walk over the
    patch's asserted FK values. The create slice mirrors
    ``resolve_fk_target_pk``: it resolves FK values while building create
    kwargs, so a guard blind to create FKs couldn't mirror it. The
    M2M-member-onto-deleted analogue (a relationship membership, not an FK) is
    out of scope here.
    """
    # Right operand: every entity this patch soft-deletes (root + cascade), via
    # the same ``cascade_targets`` walk ``plan_soft_delete`` uses, so the guard's
    # deleted set can't drift from the real delete footprint.
    deleted: set[tuple[type[LinkableModel], PublicId]] = set()
    for entry in doc.claims:
        if not isinstance(entry, DeleteEntry):
            continue
        try:
            model_class = _resolve_model_class(entry)
        except PatchError:
            continue  # unresolvable entity_type errors with per-entry attribution
        existing = registry.lookup_existing(model_class, entry.public_id)
        if existing is None:
            continue  # no such record to delete; errors per-entry later
        # Lifecycle is a discovered capability (see ``LinkableClaimModel``): only
        # a lifecycle-bearing target is soft-deletable, so a lifecycle-less one
        # contributes nothing to the delete footprint (``_add_delete`` rejects it
        # during apply). Skip it here rather than over-reject the reassignment.
        if not isinstance(existing, LifecycleStatusModel):
            continue
        # The core walk yields ``LifecycleStatusModel``; narrow each member to
        # read its canonical ``public_id`` (every cascade member is linkable).
        for member in cascade_targets(existing):
            target = require_linkable(member)
            deleted.add((type(target), target.public_id))

    if not deleted:
        return

    # Left operand: every FK value the patch *asserts*, across creates and edits.
    claim_fields_by_model: dict[type[LinkableClaimModel], dict[str, str]] = {}
    for entry in doc.claims:
        if not isinstance(entry, (CreateEntry, EditEntry)):
            continue
        try:
            model_class = _resolve_model_class(entry)
        except PatchError:
            continue
        claim_fields = claim_fields_by_model.setdefault(
            model_class, get_claim_fields(model_class)
        )
        for field_name, value in entry.fields.items():
            if field_name not in claim_fields:
                continue  # relationship namespaces / unknown fields, errored later
            django_field = model_class._meta.get_field(field_name)
            if not isinstance(django_field, models.ForeignKey):
                continue
            # Canonicalize exactly as plan-time FK resolution does, so a
            # whitespace-padded or numeric value can't slip the guard yet still
            # resolve onto the deleted entity (``resolve_fk_target_pk``
            # str-casts and trims before the public_id lookup). One shared
            # definition.
            public_id = normalize_fk_value(value)
            if public_id is None:
                continue  # falsy/blank FK value resolves to nothing
            target_model = django_field.related_model
            assert isinstance(target_model, type)  # resolved FK target
            if not issubclass(target_model, LinkableClaimModel):
                continue  # only addressable claim subjects can be in `deleted`
            if (target_model, public_id) in deleted:
                raise PatchError(
                    f"{entry.ref}: {field_name!r} points at "
                    f"{target_model.entity_type}.{public_id}, which this patch "
                    f"deletes (its root or a cascade child) — a live reference to a "
                    f"soft-deleted entity would dangle; point it elsewhere or "
                    f"don't delete the target"
                )


def _classify_inline_cites(
    entry: CreateEntry | EditEntry,
    model_class: type[LinkableClaimModel],
) -> dict[str, dict[CiteHandle, CiteSpec]]:
    """Validate this entry's inline ``[[cite:...]]`` markers against its ``cites:`` map.

    Scans **every** markdown field of the entry (the gate — a marker with no
    backing never survives), classifies each handle by strict grammar, enforces
    marker↔map correspondence, and returns ``{field_name: {numeric_handle:
    CiteSpec}}`` for each markdown field carrying ≥1 *new*-cite marker (the
    minting payload :func:`_emit_direct` attaches to its assertion). All checks
    are DB-free; existing-slug validity is enforced downstream by
    ``convert_authoring_to_storage`` (raises ``Cite not found`` on a bad slug).
    """
    markdown_fields = set(get_markdown_fields(model_class))
    md_values = {
        k: v
        for k, v in entry.fields.items()
        if k in markdown_fields and isinstance(v, str)
    }
    if entry.cites and not md_values:
        raise PatchError(
            f"{entry.ref}: 'cites:' requires a markdown-field claim to bind to — "
            f"none of this entry's fields is a citable description field"
        )

    per_field_numeric: dict[str, set[CiteHandle]] = {}
    all_numeric: set[CiteHandle] = set()
    for field_name, value in md_values.items():
        for handle in _CITE_MARKER_RE.findall(value):
            if _NUMERIC_HANDLE_RE.match(handle):
                per_field_numeric.setdefault(field_name, set()).add(handle)
                all_numeric.add(handle)
            elif _SLUG_HANDLE_RE.match(handle):
                continue  # existing-cite slug — resolved later by conversion
            else:
                raise PatchError(
                    f"{entry.ref}: malformed inline citation '[[cite:{handle}]]' in "
                    f"{field_name!r} — a handle must be all-digits (a new citation, "
                    f"needs a 'cites:' entry) or all-lowercase-letters (an existing "
                    f"cite slug); this rejects a raw-pk '[[cite:id:N]]'"
                )

    # Correspondence (DB-free, loud). A slug-keyed ``cites:`` entry is its own
    # misuse — check it before the generic "unreferenced" case so the message is
    # specific.
    cite_handles = set(entry.cites)
    slug_keyed = {h for h in cite_handles if not _NUMERIC_HANDLE_RE.match(h)}
    if slug_keyed:
        raise PatchError(
            f"{entry.ref}: 'cites:' key(s) {sorted(slug_keyed)} must be numeric "
            f"handles (e.g. '1') — an existing cite is named by its slug marker, "
            f"not declared in 'cites:'"
        )
    missing = all_numeric - cite_handles
    if missing:
        raise PatchError(
            f"{entry.ref}: inline citation handle(s) {sorted(missing)} have no "
            f"'cites:' entry to mint from"
        )
    unused = cite_handles - all_numeric
    if unused:
        raise PatchError(
            f"{entry.ref}: 'cites:' entr(y/ies) {sorted(unused)} are not referenced "
            f"by any '[[cite:N]]' marker"
        )

    return {
        field_name: {h: entry.cites[h] for h in handles}
        for field_name, handles in per_field_numeric.items()
    }


def _no_such_record_message(
    entry: EditEntry,
    model_class: type[LinkableClaimModel],
    all_created_ids: AbstractSet[_CreatedKey],
) -> str:
    """Diagnostic for an edit that resolves to no record (seed, prior patch *or* this one).

    If this patch creates the record but the create appears *below* this edit, say
    so — the single-pass create registry can't see it
    yet, but the pre-scanned ``all_created_ids`` can. Otherwise it genuinely
    doesn't exist anywhere.
    """
    if _CreatedKey(model_class, entry.public_id) in all_created_ids:
        return (
            f"{entry.ref}: edits a {entry.entity_type} created later in this patch — "
            f"move its 'create: true' entry above this edit (a create must precede "
            f"the edits that refine it)"
        )
    return f"{entry.ref}: no such {entry.entity_type} (add create:true to create it)"


def _reject_directives_on_same_patch_create(entry: EditEntry) -> None:
    """Reject directives that have no meaning on a record created in this same patch.

    A same-patch create has no prior DB state, so ``retract:`` (deactivate a
    prior claim) and ``remove:`` (tombstone a prior member) are meaningless —
    only additional field assertions, each its own separately-attributed
    ChangeSet, refine the new record.
    """
    if entry.retract:
        raise PatchError(
            f"{entry.ref}: 'retract:' can't apply to a record created earlier in "
            f"this same patch — it has no prior claims to retract"
        )
    if entry.remove:
        raise PatchError(
            f"{entry.ref}: 'remove:' can't apply to a record created earlier in "
            f"this same patch — it has no prior members to remove"
        )


def _process_entry(
    plan: IngestPlan,
    entry: PatchEntry,
    *,
    source: Source,
    rel_namespaces: frozenset[Namespace],
    rel_fields_by_model: RelFieldsByModel,
    registry: PatchEntityRegistry,
    all_created_ids: AbstractSet[_CreatedKey],
) -> _EntryResult:
    """Resolve, validate and emit one claim entry; return its cross-entry contribution.

    All DB reads and plan mutations for the entry happen here. The entry kind is
    its parsed type — the illegal directive combinations were already rejected in
    ``_parse_entry_body``, so each branch only does its own DB-dependent work. The
    per-entry provenance-carrier check is enforced inline; the returned
    :class:`_EntryResult` carries only what ``_validate_plan_wide`` needs.
    """
    note, cite_specs = _parse_provenance(entry)
    model_class = _resolve_model_class(entry)
    ct_id = ContentType.objects.get_for_model(model_class).pk
    existing = registry.lookup_existing(model_class, entry.public_id)
    # Self-referential child→parent edges this entry asserts, returned on the
    # _EntryResult for the plan-wide acyclicity guard. A delete asserts none.
    hierarchy_edges: list[_HierarchyEdge] = []

    # A delete carries no field assertions and no relationship work, so it
    # finishes here, registering every soft-deleted entity (root + cascade) with
    # the plan-wide guard as a *delete footprint*: that footprint is exclusive, so
    # any other entry touching one of these entities is rejected.
    if isinstance(entry, DeleteEntry):
        if entry.cites:
            raise PatchError(
                f"{entry.ref}: 'cites:' requires a markdown-field claim to bind to — "
                f"a delete entry takes no field assertions"
            )
        if existing is None:
            raise PatchError(f"{entry.ref}: no such {entry.entity_type} to delete")
        affected = _add_delete(plan, existing, entry, note=note, cite_specs=cite_specs)
        contributions: dict[_TargetKey, _TargetContribution] = {
            tkey: _TargetContribution(
                ref=entry.ref,
                from_delete=True,
                retracted_fields=frozenset(),
                asserted_fields=frozenset(),
                asserted_members=frozenset(),
                deferred_member_ids=frozenset(),
                removed_members={},
            )
            for tkey in affected
        }
        return _EntryResult(
            matched=True, contributions=contributions, hierarchy_edges=hierarchy_edges
        )

    target: _Target
    retracted_any = False  # set by the edit branch; a real retraction carries a note
    if isinstance(entry, CreateEntry):
        if existing is not None:
            raise PatchError(
                f"{entry.ref}: create:true but a {entry.entity_type} with this "
                f"public_id already exists"
            )
        if registry.has_create_ref(entry.ref):
            raise PatchError(f"{entry.ref}: duplicate create entry in this patch")
        registry.mark_create_ref(entry.ref)
        _add_create(plan, model_class, entry, entry.ref, registry=registry, note=note)
        # Register after _add_create, so a create's own *FK fields* (resolved
        # inside _add_create against earlier creates) can't point at itself. NB
        # this entry's *relationship* fields are emitted below, after this line,
        # so a same-entry self-referential member (theme_parent/
        # gameplay_feature_parent) IS resolvable here — self-link and cycle
        # safety for those is enforced separately by the plan-wide hierarchy
        # guard, not by registration timing.
        registry.register_create(model_class, entry.public_id, handle=entry.ref)
        target = _Target(handle=entry.ref)
    else:
        if existing is None:
            # Not in the seed or an earlier patch — but it may be created earlier
            # in *this* patch. Resolve against the same-patch create registry by
            # the FK-style key (_add_create's own field claims resolve this way),
            # and emit this entry's field asserts handle-targeted: a second,
            # separately-attributed ChangeSet of refinements on the new record.
            ref_handle = registry.created_handle(model_class, entry.public_id)
            if ref_handle is None:
                raise PatchError(
                    _no_such_record_message(entry, model_class, all_created_ids)
                )
            # Only field assertions are meaningful on a brand-new record: there's
            # no prior DB state to retract or remove against.
            _reject_directives_on_same_patch_create(entry)
            target = _Target(handle=ref_handle)
        else:
            retracted_any = _add_retractions(
                plan,
                model_class,
                existing,
                entry,
                ct_id,
                source,
                rel_namespaces,
                note=note,
            )
            target = _Target(content_type_id=ct_id, object_id=existing.pk)

    # Inline-citation markers in the entry's markdown fields: validate grammar +
    # marker↔``cites:`` correspondence (DB-free) and get the per-field new-cite
    # minting payloads. Runs once over the whole entry before emitting, so a
    # marker in any markdown field is gated even if that field is emitted later.
    inline_cites_by_field = _classify_inline_cites(entry, model_class)

    # Shared field loop (create + edit). Track which scalar/FK fields and which
    # relationship members this entry asserts on its target — every target (an
    # existing entity, or a same-patch create / its companion edits, both keyed by
    # handle) feeds the plan-wide disjoint-claims guard — and whether any real
    # claim carrier was written (for the provenance check).
    asserted_fields: set[str] = set()
    asserted_members: set[ClaimKey] = set()
    deferred_member_ids: set[str] = set()
    carrier_written = False
    claim_fields = get_claim_fields(model_class)
    for key, value in entry.fields.items():
        if key == LIFECYCLE_STATUS_FIELD:
            # ``status`` is lifecycle state, not a free-form claim. Writing it
            # directly would bypass the delete planner's blocker check and
            # cascade — route lifecycle changes through the directive.
            raise PatchError(
                f"{entry.ref}: {LIFECYCLE_STATUS_FIELD!r} is lifecycle state — "
                f"soft-delete with 'delete: true', not a direct claim"
            )
        if key in claim_fields:
            _emit_direct(
                plan,
                model_class,
                key,
                value,
                target,
                entry,
                registry=registry,
                note=note,
                cite_specs=cite_specs,
                inline_cites=inline_cites_by_field.get(key, {}),
            )
            carrier_written = True
            asserted_fields.add(key)
        elif key in rel_namespaces:
            emit = _emit_relationship(
                plan,
                model_class,
                key,
                value,
                target,
                entry,
                registry=registry,
                note=note,
                cite_specs=cite_specs,
            )
            rel_fields_by_model[model_class].add(key)
            hierarchy_edges.extend(emit.hierarchy_edges)
            if emit.carrier_written:
                carrier_written = True
            # Concrete claim_keys feed the clash + disjoint guards; a deferred
            # (same-patch) member has no claim_key yet, so its whole composite
            # identity (a pk or handle per slot) rides a separate disjoint key.
            # Keying on the *full* composite — not a single handle — keeps two
            # members that share one deferred slot (e.g. two persons crediting the
            # same same-patch-created role) distinct rather than false-duplicates.
            asserted_members.update(emit.clash_keys)
            deferred_member_ids.update(f"{key} {m}" for m in emit.deferred_members)
        else:
            raise PatchError(f"{entry.ref}: unknown field {key!r}")

    # Relationship-member removals (exists=false supersede). Only an EditEntry
    # carries ``remove`` (create/delete reject it at parse time).
    removed_members: dict[ClaimKey, str] = {}
    if isinstance(entry, EditEntry) and entry.remove:
        assert existing is not None  # an EditEntry always matched above
        removal = _add_removals(
            plan,
            model_class,
            existing,
            entry,
            ct_id,
            source,
            rel_namespaces,
            rel_fields_by_model,
            note=note,
            cite_specs=cite_specs,
        )
        removed_members = removal.removed_members
        carrier_written = carrier_written or removal.carrier_written

    _check_provenance_carrier(
        entry,
        note=note,
        cite_specs=cite_specs,
        carrier_written=carrier_written,
        retracted_any=retracted_any,
    )

    if isinstance(entry, CreateEntry):
        # A create contributes its authored + identity claims under its handle, so
        # the disjoint-claims guard spans the create and any companion edits that
        # refine it. The slug/public-id claim is emitted by
        # _add_create *outside* the field loop, so add it here under the exact
        # condition _add_create emits it (the public id is itself a claim field —
        # true for slug-identified entities, false for a derived public id like
        # Location.location_path, whose authored ``slug`` already rode the loop).
        # A create doesn't count toward records_matched.
        create_fields = set(asserted_fields)
        pid_field = model_class.public_id_field
        if pid_field in claim_fields:
            create_fields.add(pid_field)
        contribution = _TargetContribution(
            ref=entry.ref,
            from_delete=False,
            retracted_fields=frozenset(),
            asserted_fields=frozenset(create_fields),
            asserted_members=frozenset(asserted_members),
            deferred_member_ids=frozenset(deferred_member_ids),
            removed_members={},
        )
        return _EntryResult(
            matched=False,
            contributions={entry.ref: contribution},
            hierarchy_edges=hierarchy_edges,
        )

    contribution = _TargetContribution(
        ref=entry.ref,
        from_delete=False,
        retracted_fields=frozenset(entry.retract),
        asserted_fields=frozenset(asserted_fields),
        asserted_members=frozenset(asserted_members),
        deferred_member_ids=frozenset(deferred_member_ids),
        removed_members=removed_members,
    )
    if existing is not None:
        return _EntryResult(
            matched=True,
            contributions={EntityKey(ct_id, existing.pk): contribution},
            hierarchy_edges=hierarchy_edges,
        )
    # Registry-resolved companion edit on a same-patch create: key by the handle
    # so its claims join the create's contribution in the disjoint-claims guard.
    # matched=False — it refined a same-patch create, not a DB row (the record is
    # already counted by the create).
    assert target.handle is not None
    return _EntryResult(
        matched=False,
        contributions={target.handle: contribution},
        hierarchy_edges=hierarchy_edges,
    )


def _check_provenance_carrier(
    entry: CreateEntry | EditEntry,
    *,
    note: str,
    cite_specs: tuple[CiteSpec, ...],
    carrier_written: bool,
    retracted_any: bool,
) -> None:
    """Reject a note/cite with no emitted claim to attach to (it would vanish).

    ``cite`` must ride an authored field assertion; ``note`` also rides a create's
    scaffolding claims or a real retraction. (A DeleteEntry carries its own
    ``status=deleted`` carrier and never reaches here.)

    Neither ``remove`` nor ``retract`` counts as a note carrier on its own — only
    when it actually writes something. A removal that supersedes a member emits
    an assertion (so ``carrier_written`` already covers it) and a retraction that
    deactivates a claim is reported via ``retracted_any``; a *no-op* of either
    emits nothing, so ``_persist`` makes no ChangeSet and the note would vanish.
    This keeps note in step with cite, which likewise requires a real carrier.
    """
    if cite_specs and not carrier_written:
        raise PatchError(
            f"{entry.ref}: cite has no field to attach to — cite a field you're "
            f"also asserting (a retraction, a no-op removal, a field-less "
            f"create, or an empty relationship like 'tag: []' can't carry one)"
        )
    note_has_carrier = (
        carrier_written or isinstance(entry, CreateEntry) or retracted_any
    )
    if note and not note_has_carrier:
        raise PatchError(
            f"{entry.ref}: note has nothing to attach to — assert a field, "
            f"retract a currently-claimed field, create, or remove a "
            f"currently-present member (a no-op carries nothing)"
        )


def _existing_parent_edges(
    model_class: type[LinkableClaimModel],
) -> dict[PublicId, set[PublicId]]:
    """Current resolved child→parent public_id edges for a hierarchy model.

    ``parents`` is declared only on the concrete hierarchy models
    (``Theme``/``GameplayFeature``), not the ``LinkableClaimModel`` base this
    helper is typed against, so django-stubs can't see it; the two ignores are
    confined to this boundary helper. Only called for models that actually have
    the hierarchy ``parents`` M2M (those with a self-referential FK relationship).
    """
    edges: dict[PublicId, set[PublicId]] = {}
    queryset = model_class._default_manager.prefetch_related("parents")  # type: ignore[misc]
    for inst in queryset:
        parents: models.Manager[LinkableClaimModel] = inst.parents  # type: ignore[attr-defined]
        edges[inst.public_id] = {p.public_id for p in parents.all()}
    return edges


def _reaches_via_parents(
    parent_map: dict[PublicId, set[PublicId]], start: PublicId, target: PublicId
) -> bool:
    """Walking parent edges up from *start*, is *target* reachable?

    ``start == target`` reaches trivially (used for the self-link case). Tolerant
    of pre-existing cycles in the graph via the ``seen`` guard.
    """
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(parent_map.get(node, ()))
    return False


def _validate_hierarchy_acyclic(hierarchy_edges: list[_HierarchyEdge]) -> None:
    """Reject self-parent links and cycles in self-referential hierarchies.

    The patch path otherwise bypasses the API's ``plan_parent_claims`` guard, so
    a patch could assert ``gameplay_feature_parent: [self]`` or two mutually-
    referencing parents and silently corrupt the DAG (the resolver materializes
    whatever wins, with no self/cycle check).

    Conservative by design: the post-patch parent graph is the current resolved
    edges *plus* this patch's added edges, ignoring removals — so it never misses
    a cycle (a removal can only break one, and a removal that's a no-op for this
    source leaves the edge in place via another). A patch that both removes and
    re-adds around an edge may be over-rejected; split it across patches.
    """
    by_model: dict[type[LinkableClaimModel], list[_HierarchyEdge]] = defaultdict(list)
    for edge in hierarchy_edges:
        by_model[edge.model_class].append(edge)
    for model_class, edges in by_model.items():
        # Post-patch graph: current resolved edges + this patch's added edges.
        parent_map = _existing_parent_edges(model_class)
        for edge in edges:
            if edge.child == edge.parent:
                raise PatchError(
                    f"{edge.ref}: a {model_class.entity_type} cannot be its own "
                    f"parent ({edge.namespace})"
                )
            parent_map.setdefault(edge.child, set()).add(edge.parent)
        for edge in edges:
            # Adding child→parent closes a cycle iff parent already reaches child.
            if _reaches_via_parents(parent_map, edge.parent, edge.child):
                raise PatchError(
                    f"{edge.ref}: {edge.namespace} would create a cycle "
                    f"({edge.child} → {edge.parent} → … → {edge.child})"
                )


def _validate_plan_wide(results: list[_EntryResult]) -> None:
    """Run the cross-entry guards over all processed entries.

    With per-entry ChangeSets, several entries may target one record — an existing
    entity *or* a same-patch create (keyed by its handle) — *provided* the claims
    they touch are disjoint. Each entry mints its own ChangeSet, and a claim_key
    shared by two entries would collapse in ``_build_claims`` /
    ``_process_retractions``, silently dropping one entry's grouping. Merges each
    entry's per-target contributions, enforcing on insert:

    1. **Disjoint claims.** No scalar/FK field, concrete or deferred
       relationship member, or member tombstone may be asserted by two entries on
       one target; no field retracted by two entries.
    2. **Delete exclusivity.** A delete soft-deletes its root +
       cascade as one ChangeSet, so no other entry may target any entity in that
       footprint.
    3. **No field both retracted and asserted** on one target (the assert wins,
       the retract is a silent no-op).
    4. **No member both asserted present and removed** on one target (both write
       the same claim_key — one would clobber the other).
    """
    target_ref: dict[_TargetKey, str] = {}
    is_delete: dict[_TargetKey, bool] = defaultdict(bool)
    entry_count: dict[_TargetKey, int] = defaultdict(int)
    retracted_fields: dict[_TargetKey, set[str]] = defaultdict(set)
    asserted_fields: dict[_TargetKey, set[str]] = defaultdict(set)
    asserted_members: dict[_TargetKey, set[ClaimKey]] = defaultdict(set)
    deferred_members: dict[_TargetKey, set[str]] = defaultdict(set)
    removed_members: dict[_TargetKey, dict[ClaimKey, str]] = defaultdict(dict)

    def _reject_dup[T](
        incoming: AbstractSet[T], seen: AbstractSet[T], ref: str, what: str
    ) -> None:
        dup = incoming & seen
        if dup:
            labels = ", ".join(sorted(str(d) for d in dup))
            raise PatchError(
                f"{ref}: {what} {labels} set by more than one entry on this record "
                f"— each entry is its own changeset, so combine them into one entry"
            )

    for result in results:
        for tkey, c in result.contributions.items():
            ref = c.ref
            entry_count[tkey] += 1
            target_ref[tkey] = ref
            if c.from_delete:
                is_delete[tkey] = True
            _reject_dup(c.asserted_fields, asserted_fields[tkey], ref, "field")
            _reject_dup(
                c.retracted_fields, retracted_fields[tkey], ref, "retracted field"
            )
            _reject_dup(c.asserted_members, asserted_members[tkey], ref, "member")
            _reject_dup(c.deferred_member_ids, deferred_members[tkey], ref, "member")
            _reject_dup(
                c.removed_members.keys(),
                removed_members[tkey].keys(),
                ref,
                "removed member",
            )
            retracted_fields[tkey] |= c.retracted_fields
            asserted_fields[tkey] |= c.asserted_fields
            asserted_members[tkey] |= c.asserted_members
            deferred_members[tkey] |= c.deferred_member_ids
            removed_members[tkey].update(c.removed_members)

    # Decision 5: a delete footprint is exclusive over root + cascade.
    for tkey, deleting in is_delete.items():
        if deleting and entry_count[tkey] > 1:
            raise PatchError(
                f"{target_ref[tkey]}: another entry targets an entity this patch "
                f"deletes (its root or a cascade child) — a delete must be the only "
                f"entry touching the entities it removes"
            )

    for tkey, r_fields in retracted_fields.items():
        both = sorted(r_fields & asserted_fields.get(tkey, set()))
        if both:
            raise PatchError(
                f"{target_ref[tkey]}: cannot both retract and assert "
                f"{', '.join(both)} for this entity"
            )

    for tkey, removed in removed_members.items():
        clashing = set(removed) & asserted_members.get(tkey, set())
        if clashing:
            labels = sorted(removed[claim_key] for claim_key in clashing)
            raise PatchError(
                f"{target_ref[tkey]}: cannot both assert and remove "
                f"{', '.join(labels)} for this entity"
            )


def _plan_citation_sources(plan: IngestPlan, sources: list[SourceNode]) -> None:
    """Validate `sources:` nodes (read phase) and register the upsert hook.

    Field-validates each node now — so a bad ``source_type``/date/URL fails as a
    clean :class:`PatchError` at ``--dry-run`` rather than mid-transaction — then
    appends a pre-write hook that additively get-or-creates the sources when the
    plan is applied. The upsert itself never errors on a collision (see
    ``ensure_root_source``); only author-controllable shape/value errors raise.

    Also registers a dry-run preview hook so a host collision (recognition hosts
    spanning >1 root → a whole-node skip) surfaces as a warning at ``--dry-run``,
    not only at live apply. The two hooks are mutually exclusive by path, so the
    collision never double-warns.
    """
    if not sources:
        return
    for i, node in enumerate(sources):
        try:
            validate_root_source(node)
        except ValidationError as exc:
            raise PatchError(
                f"sources[{i}] ({node['name']!r}): {_format_validation_error(exc)}"
            ) from exc
    plan.pre_write_hooks.append(_make_sources_hook(sources, plan.source.actor))
    plan.dry_run_preview_hooks.append(_make_sources_preview_hook(sources))


def _format_validation_error(exc: ValidationError) -> str:
    """Render a model ``ValidationError`` field-first (so the bad field is named)."""
    try:
        message_dict = exc.message_dict
    except AttributeError:
        return "; ".join(exc.messages)
    return "; ".join(
        f"{field}: {' '.join(messages)}" for field, messages in message_dict.items()
    )


def _make_sources_hook(sources: list[SourceNode], actor: Actor) -> PreWriteHook:
    """Build the pre-write hook that upserts a patch's citation sources.

    The closure owns the catalog-side accounting: ``ensure_root_source`` is
    source-agnostic (plain ``list[str]`` sink + a result tuple), and the hook
    folds its result into the ``RunReport`` — keeping the catalog ``RunReport``
    type out of the citation app. ``actor`` is the patch's ``Source`` actor, so
    the citation rows a patch creates are attributed to it.
    """

    def hook(report: RunReport) -> None:
        for node in sources:
            result = ensure_root_source(node, actor=actor, warnings=report.warnings)
            if result.source_created:
                report.sources_created += 1
            else:
                report.sources_skipped += 1
            report.source_links_created += result.links_created

    return hook


def _make_sources_preview_hook(sources: list[SourceNode]) -> DryRunPreviewHook:
    """Build the dry-run preview hook for a patch's citation sources.

    Read-only counterpart to ``_make_sources_hook``: a pure committed-state
    ``detect_host_collision`` read per node, appending the spans-two-roots warning
    so an author sees the whole-node skip at ``--dry-run`` before publishing. The
    live path runs the authoritative ``_make_sources_hook`` instead, so the
    collision warns exactly once on each path.
    """

    def hook(report: RunReport) -> None:
        for node in sources:
            warning = detect_host_collision(node)
            if warning is not None:
                report.warnings.append(warning)

    return hook
