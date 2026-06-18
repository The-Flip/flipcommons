"""Live write path: create entities, persist claims, attach provenance, resolve.

Everything the live path does that touches the DB for real: bulk-create planned
entities and resolve their handles (:func:`_create_entities`,
:func:`_patch_handles`), mint inline + per-field citations
(:func:`_materialize_inline_citations`, :func:`_attach_plan_citations`), collect
per-entry provenance (:func:`_collect_plan_provenance`), and write the diffed
claims into ChangeSets grouped per-entry (patch) or per-entity (ingest)
(:func:`_persist` and its ``_persist_*`` modes). :func:`_resolve` then
materialises derived values on affected entities.

Depends on :mod:`.claims` (``RetractEntry``, the empty-diff guard). Holds the two
catalog touchpoints — ``build_relationship_claim`` in :func:`_patch_handles` and
``resolve_all_entities`` in :func:`_resolve` — as lazy imports, the only places
the otherwise source-agnostic engine reaches into the catalog app.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import cast

from django.contrib.contenttypes.models import ContentType

from apps.catalog.ingestion.apply.claims import (
    RetractEntry,
    _reject_empty_diff_provenance,
)
from apps.catalog.ingestion.plan import (
    CitationRef,
    CiteHandle,
    EntryIndex,
    Handle,
    IngestPlan,
    PlannedClaimAssert,
    PlannedEntityCreate,
    ResolveHook,
)
from apps.core.types import ClaimIdentity, EntityKey
from apps.provenance.models import ChangeSet, Claim, ClaimControlledModel, IngestRun

# Per-entry / per-claim provenance maps produced by ``_collect_plan_provenance``
# and consumed by ``_persist`` / ``_attach_plan_citations``. ``EntryNotes`` keys
# each entry's note by its ``EntryIndex`` (one ChangeSet, one note per patch
# entry); ``ClaimEntryIndex`` resolves a built claim back to its entry for
# per-entry ChangeSet grouping; ``ClaimCitations`` keys per claim identity.
type EntryNotes = dict[EntryIndex, str]
type ClaimCitations = dict[ClaimIdentity, CitationRef]
type ClaimEntryIndex = dict[ClaimIdentity, EntryIndex]


def _create_entities(
    entities: list[PlannedEntityCreate],
) -> dict[Handle, EntityKey]:
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

    handle_map: dict[Handle, EntityKey] = {}

    # Group consecutive entities of the same model class into batches.
    # A batch is flushed when the model class changes OR when an entity's
    # handle_refs reference a handle in the current pending batch (those
    # PKs aren't available until the batch is bulk_created).
    batches: list[list[PlannedEntityCreate]] = []
    current_handles: set[Handle] = set()
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
    handle_map: dict[Handle, EntityKey],
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
    from apps.provenance.claims import build_relationship_claim

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
      built claims into per-entry ChangeSets. Recorded for *every* assertion —
      note-less ones included — so a multi-entry patch still groups correctly.
      The front end's second pass stamps every assertion, so the index is
      always present here.

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
        # Every assertion is stamped by the front end's second pass.
        assert pca.entry_index is not None
        claim_entry_index[ident] = pca.entry_index
        if not pca.note and pca.citation_ref is None:
            continue  # the common case: a plain assertion with no note/cite
        if pca.note:
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

    ChangeSets are minted one per authoring patch entry (``entry_index``, carrying
    that entry's note) — see :func:`_persist_per_entry`.
    """
    if not to_create and not retract_entries:
        return

    if superseded_ids:
        Claim.objects.filter(pk__in=superseded_ids).update(is_active=False)

    _persist_per_entry(run, to_create, retract_entries, entry_notes, claim_entry_index)


def _link_to_changesets[K](
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
    group_to_cs: dict[K, ChangeSet],
    claim_group: Callable[[Claim], K],
    retract_group: Callable[[RetractEntry], K],
) -> None:
    """Point each new claim and retraction at its ChangeSet, then write.

    The changeset-linking tail of ``_persist_per_entry``, parameterized by the
    grouping key via the ``claim_group`` / ``retract_group`` extractors over an
    already-built ``group_to_cs``. Kept generic over the key ``K`` so a second
    grouping mode (e.g. per-entity, for a future non-patch source) can reuse it
    without re-deriving this. Retracted claims are deactivated in bulk per
    ChangeSet, stamped ``retracted_by_changeset``.
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
