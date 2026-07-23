"""Live write path: create entities, persist claims, attach provenance, resolve.

Everything the live path does that touches the DB for real: bulk-create planned
entities and resolve their handles (:func:`_create_entities`,
:func:`_patch_handles`), mint inline + per-field citations
(:func:`_materialize_inline_citations`, :func:`_attach_plan_citations`), collect
per-entry provenance (:func:`_collect_plan_provenance`), and write the diffed
claims into ChangeSets grouped per-entry (patch) or per-entity (ingest)
(:func:`_persist` and its ``_persist_*`` modes). :func:`_resolve` then
materialises derived values on affected entities.

Depends on :mod:`.claims` (``RetractEntry``, the empty-diff guard). Reaches the
substrate through two provenance helpers, held as lazy imports:
``build_relationship_claim`` in :func:`_patch_handles` and the
``resolve_entities_bulk`` dispatch in :func:`_resolve` — the latter routes to the
domain's registered resolver without this engine importing the domain.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple, assert_never, cast

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from apps.actors.models import Actor
from apps.claim_ingest.apply.claims import (
    RetractEntry,
    _reject_empty_diff_provenance,
)
from apps.claim_ingest.plan import (
    ChangedRelationshipFields,
    CitationRef,
    CiteHandle,
    CiteSpec,
    EntryIndex,
    Handle,
    IngestPlan,
    IsbnCitationRef,
    PlannedClaimAssert,
    PlannedEntityCreate,
    SchemeCitationRef,
    SourceCitationRef,
    WebCitationRef,
)
from apps.core.types import (
    CitationSourceId,
    ClaimIdentity,
    ContentTypeId,
    EntityKey,
)
from apps.provenance.models import ChangeSet, Claim, ClaimControlledModel, IngestRun
from apps.provenance.types import ChangeSetId, ClaimId

type EntryNotes = dict[EntryIndex, str]
"""Each patch entry's note keyed by its ``EntryIndex`` — one ChangeSet, one note
per entry. Produced by ``_collect_plan_provenance``, consumed by ``_persist``."""

type ClaimCitations = dict[ClaimIdentity, tuple[CiteSpec, ...]]
"""Per-claim ``CiteSpec``s keyed by claim identity — never per entry, so a
citation never bleeds onto unrelated claims sharing the entity. Produced by
``_collect_plan_provenance``, consumed by ``_attach_plan_citations``."""

type ClaimEntryIndex = dict[ClaimIdentity, EntryIndex]
"""Resolves a built claim back to its authoring entry, for per-entry ChangeSet
grouping. Produced by ``_collect_plan_provenance``, consumed by ``_persist``."""

type CiteSourceCache = dict[CitationRef, CitationSourceId]
"""Memoizes ``CitationRef`` → resolved ``CitationSource`` pk within one apply, so a
cite reused across claims/footnotes resolves (and dedups) once. Threaded through
``_resolve_cite_source_id`` by both the field-``cite:`` and inline-footnote paths."""

type HandleMap = dict[Handle, EntityKey]
"""Resolves each ``create:``'s temporary ``Handle`` to its real ``EntityKey``
(ct_id, pk) after bulk-create. Produced by ``_create_entities``, threaded into
``_patch_handles`` to patch handle-targeted assertions and identity refs."""


def _create_entities(
    entities: list[PlannedEntityCreate],
) -> HandleMap:
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

    handle_map: HandleMap = {}

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
    handle_map: HandleMap,
) -> None:
    """Resolve temporary handles to real PKs after entity creation.

    Three kinds of handle resolution:

    1. **Target handles** — ``pca.handle`` references the entity this
       claim is *about*.  Patches ``object_id`` and ``content_type_id``.

    2. **Value refs** — ``pca.value_ref`` references the entity a direct
       FK claim points *at*; its new PK becomes the claim ``value``.

    3. **Identity refs** — ``pca.identity_refs`` references entities
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
        if pca.value_ref is not None:
            pca.value = handle_map[pca.value_ref].object_id
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
    """Gather per-entry ``note``/``cite_specs`` and the claim→entry grouping map.

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
        if not pca.note and not pca.cite_specs:
            continue  # the common case: a plain assertion with no note/cite
        if pca.note:
            entry_notes[pca.entry_index] = pca.note
        if pca.cite_specs:
            claim_citations[ident] = pca.cite_specs
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


def _cite_resolution_error(ref: CitationRef, exc: Exception) -> str:
    """Build a patch-readable message naming the cite that failed to resolve.

    The raw resolver exception names no cite — a malformed URL surfaces as the
    bare ``URLField`` "Enter a valid URL.", a missing root as a
    ``DoesNotExist``, a bad identifier as a ``ValueError`` — so a ``PatchError``
    built from it alone can't point an author at the offending line. Prefix the
    cite descriptor (the URL, or ``scheme:identifier``), in scope here on the
    ``CitationRef``, so the wrapped ``ValidationError`` carries it through.

    A web cite's ``archive`` link validates separately in
    ``get_or_create_web_source`` and can be the offender while the page URL is
    fine; the bare ``URLField`` message is identical for both, so name *both*
    URLs when an archive is present — the author can then spot the malformed one.
    """
    match ref:
        case WebCitationRef(url=url, archive_url=archive_url):
            descriptor = repr(url)
            if archive_url:
                descriptor += f" (archive {archive_url!r})"
        case SchemeCitationRef(scheme=scheme, identifier=identifier):
            descriptor = repr(f"{scheme}:{identifier}")
        case IsbnCitationRef(isbn=isbn):
            descriptor = repr(f"isbn:{isbn}")
        case SourceCitationRef(root_slug=root_slug, child_slug=child_slug):
            descriptor = repr(f"{root_slug}:{child_slug}")
        case _:
            assert_never(ref)
    detail = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return f"cite {descriptor}: {detail}"


def _resolve_cite_source_id(
    ref: CitationRef, cache: CiteSourceCache, *, actor: Actor
) -> CitationSourceId:
    """Resolve a ``CitationRef`` to a ``CitationSource`` pk, memoized via ``cache``.

    Shared by the field-level ``cite:`` path (:func:`_attach_plan_citations`) and
    the inline-footnote path (:func:`_materialize_inline_citations`). Uses the
    same ``get_or_create_*`` resolvers, so source dedup, web-root matching and
    ``{url, archive}`` backfill come free. Created sources are *uncounted* — the
    resolvers return a bare ``CitationSource``, not created-ness — matching the
    field-``cite:`` stance (only the ``sources:`` block bumps the counters). A
    cite that mints a new source attributes it to ``actor`` (the patch's
    ``Source`` actor), like the ``sources:`` block.

    The resolvers fail three ways — a malformed URL/identifier (``ValidationError``
    from the leaves' ``full_clean``), an unknown scheme or bad identifier
    (``ValueError``), a missing root (``CitationSource.DoesNotExist``) — and only
    the first is caught downstream by default. Catch all three here and re-raise
    one enriched ``ValidationError`` naming the offending cite, so every failure
    mode reaches ``_apply_one`` as a clean per-patch ``PatchError`` rather than a
    raw traceback. ``ValidationError`` (not ``PatchError``) keeps this engine
    source-agnostic — ``_apply_one`` owns the mapping to ``PatchError``.
    """
    source_id = cache.get(ref)
    if source_id is None:
        from apps.citation.extractors import (
            get_isbn_source,
            get_or_create_external_source,
            get_or_create_web_source,
            get_slug_source,
        )

        try:
            match ref:
                case WebCitationRef(url=url, archive_url=archive_url):
                    source_id = get_or_create_web_source(
                        url, archive_url, created_by=actor
                    ).pk
                case SchemeCitationRef(scheme=scheme, identifier=identifier):
                    source_id = get_or_create_external_source(
                        scheme, identifier, created_by=actor
                    ).pk
                case IsbnCitationRef(isbn=isbn):
                    # Read-only: an authored work is seeded, never minted by a
                    # cite, so this arm takes no ``actor``.
                    source_id = get_isbn_source(isbn).pk
                case SourceCitationRef(root_slug=root_slug, child_slug=child_slug):
                    # Read-only like isbn: an issue is declared, never minted.
                    source_id = get_slug_source(root_slug, child_slug).pk
                case _:
                    assert_never(ref)
        except (ValidationError, ValueError, ObjectDoesNotExist) as exc:
            raise ValidationError(_cite_resolution_error(ref, exc)) from exc
        cache[ref] = source_id
    return source_id


class _SharedCiteKey(NamedTuple):
    """Identity of one shared ``CitationInstance`` within an apply.

    A changeset's claims share one instance only when the *whole* citation
    content matches — same source, locator and quote. A differing quote is a
    distinct piece of evidence even against the same source and locator.
    """

    changeset_id: ChangeSetId
    source_id: CitationSourceId
    locator: str
    quote: str


def _attach_plan_citations(
    to_create: list[Claim],
    claim_citations: ClaimCitations,
    actor: Actor,
) -> None:
    """Materialize per-claim ``CiteSpec``s as ``CitationInstance`` rows.

    Runs after ``_persist`` so created claims have PKs. A citation only rides
    a *newly written* claim: a value that diffs as unchanged produces no
    ``to_create`` entry, so re-asserting an already-correct value purely to
    add a ``cite:`` is a documented no-op (see docs/DataPatches.md).

    ``actor`` is the patch's ``Source`` actor — a ``cite:`` URL that mints a new
    citation source attributes it to the patch, like the ``sources:`` block.
    """
    if not claim_citations:
        return
    from apps.citation.models import CitationInstance
    from apps.provenance.models import ClaimCitationInstance

    # One shared instance per distinct citation per ChangeSet: claims in the
    # same entry citing the same evidence reach one row through join fan-out
    # rather than minting a clone each. Within one claim, two specs that are
    # distinct as authored can still resolve to one instance content (the same
    # URL cited bare and with an ``archive:``) — ``seen`` collapses those to
    # one join row instead of tripping the unique (claim, instance) constraint.
    source_cache: CiteSourceCache = {}
    shared: dict[_SharedCiteKey, CitationInstance] = {}
    cited: list[tuple[Claim, _SharedCiteKey]] = []
    for claim in to_create:
        specs = claim_citations.get(
            ClaimIdentity(claim.content_type_id, claim.object_id, claim.claim_key), ()
        )
        seen: set[_SharedCiteKey] = set()
        for spec in specs:
            source_id = _resolve_cite_source_id(spec.ref, source_cache, actor=actor)
            key = _SharedCiteKey(
                claim.changeset_id, source_id, spec.locator, spec.quote
            )
            if key in seen:
                continue
            seen.add(key)
            if key not in shared:
                shared[key] = CitationInstance(
                    citation_source_id=source_id,
                    locator=spec.locator,
                    quote=spec.quote,
                )
            cited.append((claim, key))
    if shared:
        CitationInstance.objects.mint_many(list(shared.values()))
        ClaimCitationInstance.objects.bulk_create(
            (
                ClaimCitationInstance(claim=claim, citation_instance=shared[key])
                for claim, key in cited
            ),
            batch_size=2000,
        )


def _materialize_inline_citations(
    assertions: list[PlannedClaimAssert], actor: Actor
) -> None:
    """Mint floating ``CitationInstance`` rows for *new* inline citations.

    For each assertion carrying ``inline_cites`` (a ``{numeric-handle:
    CiteSpec}`` map populated by the patch adapter), mints one floating
    ``CitationInstance`` per handle carrying the spec's locator/quote (no join
    rows — an inline instance is reached only by its marker), then rewrites
    that handle's
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
    from apps.citation.models import CitationInstance

    # Mint every new instance in one batch, tracking the (assertion, handle) each
    # belongs to so we can read its assigned slug back after mint_many. Minting is
    # per-assertion (i.e. per markdown field): a handle reused across two markdown
    # fields of one entry would mint one instance per field — the design's
    # per-field footnote semantics, not a shared one. Moot while every entity has
    # a single markdown field; intentional if that ever changes.
    source_cache: CiteSourceCache = {}
    instances: list[CitationInstance] = []
    owners: list[tuple[PlannedClaimAssert, CiteHandle]] = []
    for pca in cited:
        for handle, spec in pca.inline_cites.items():
            source_id = _resolve_cite_source_id(spec.ref, source_cache, actor=actor)
            instances.append(
                CitationInstance(
                    citation_source_id=source_id,
                    locator=spec.locator,
                    quote=spec.quote,
                )
            )
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
    superseded_ids: list[ClaimId],
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
        cs = group_to_cs[claim_group(claim)]
        claim.changeset_id = cs.pk
        # Denormalized copy of the ChangeSet's actor (the source of truth), so
        # each bulk Claim's actor matches its ChangeSet's — same invariant the
        # interactive path gets from ``changeset.actor``.
        claim.actor_id = cs.actor_id
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
        ChangeSet(ingest_run=run, actor=run.source.actor, note=entry_notes.get(idx, ""))
        for idx in ordered
    ]
    ChangeSet.objects.bulk_create(changesets)
    idx_to_cs = dict(zip(ordered, changesets, strict=True))
    _link_to_changesets(to_create, retract_entries, idx_to_cs, claim_idx, retract_idx)


def _resolve(
    to_create: list[Claim],
    retract_entries: list[RetractEntry],
    changed_relationship_fields: ChangedRelationshipFields,
) -> None:
    """Materialise resolved values on affected entities.

    Dispatches each affected content type to the provenance bulk resolver,
    which re-resolves scalar/FK fields for the whole subject set and the changed
    relationship namespaces (``changed_relationship_fields``) in one pass each.
    """
    from apps.provenance.resolution import resolve_entities_bulk

    affected_by_ct: dict[ContentTypeId, set[int]] = defaultdict(set)
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
        resolve_entities_bulk(
            cast(type[ClaimControlledModel], model_class),
            subject_ids=obj_ids,
            field_names=changed_relationship_fields.get(ct_id, frozenset()),
        )
