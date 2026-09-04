# Resolution Boundary: Untangling Provenance and Catalog

## Status: ✅ DONE

**What shipped (the goal).** Provenance can now trigger resolution without importing the domain. `resolve_after_mutation(entity, field_names)` exists (plus a `resolve_entities_bulk` sibling), and the motivating use case — **one-click revert** — is real: `provenance/revert.py` calls it, wired through `provenance/api.py` + `schemas.py`. All three intended callers are connected: the interactive write path (`claim_edit/claim_write.py`), the bulk pipeline (`claim_ingest`'s apply engine), and revert.

**What's different — and better — than the "Direction" section below.** This doc proposed putting the function in `catalog.resolve` with hardcoded dispatch dicts (`PARENT_RESOLVERS` / `SIMPLE_M2M_RESOLVERS` / `CUSTOM_RESOLVERS` / auto-discovered `ALIAS_RESOLVERS`) and `isinstance(MachineModel)` routing all living inside catalog. **None of that shipped.** Instead the inverted owner-registration pattern won: the seam lives in **provenance** (`provenance/resolution/_dispatch.py`) and imports zero domain symbols; catalog _registers_ a per-model `ResolveHandlers(per_entity, bulk)` pair at `CatalogConfig.ready()` (`catalog/resolve/_dispatch.py`). The namespace→resolver dispatch table this doc feared leaking into provenance was avoided entirely — each domain owns its routing behind its registered handler.

**What didn't happen — and became [Refactor](ClaimResolutionRefactor.md)'s job, not this doc's.** The `isinstance(entity, MachineModel) → resolve_model()` branch — which had moved _inside_ catalog's registered per-entity handler (`catalog/resolve/_dispatch.py`) — has since been removed in Refactor **REF1**: MachineModel now resolves through the same generic per-entity (`resolve_entity`) and bulk (`resolve_entities_bulk`) paths as every other entity. The per-entity wrapper fns this doc said to retire (`resolve_theme_aliases`, `resolve_theme_parents`, the other `resolve_*_aliases`) have since been removed — production resolves aliases and parents through the dispatch registries (`_get_alias_dispatch` / `_get_parent_dispatch`) calling the generic `_resolve_aliases` / `_resolve_parents`. The illustrative snippets below predate that and show the old hand-passed-resolver coupling.

---

## The Problem

Provenance owns claim data (Claim, ChangeSet, Source). Catalog owns what happens when claim data changes — resolving winning values into entity fields, materializing relationships, invalidating caches. But there's no clean boundary between them. Every claim mutation must trigger catalog-specific resolution, and the knowledge of _how_ to resolve is scattered across the codebase.

This coupling was tolerable when claim mutations only happened in two places: interactive edits (catalog PATCH endpoints) and bulk ingestion (management commands). Both lived in catalog or were orchestrated by catalog-aware code. But as provenance gains its own write operations — such as one-click revert — the coupling becomes a real problem. Provenance can't deactivate a claim and trigger re-resolution without importing half of catalog.

## Where the Coupling Lives

### Interactive edits: caller-driven dispatch

`execute_claims()` in `catalog/api/edit_claims.py` takes `resolve_fn` and `resolvers` as parameters. Each PATCH endpoint knows which entity type it's editing and which relationship resolvers to pass:

```python
# themes.py — caller knows to add parent/alias resolvers
resolvers = []
if data.parents is not None:
    resolvers.append(resolve_theme_parents)
if data.aliases is not None:
    resolvers.append(resolve_theme_aliases)
execute_claims(theme, specs, user=request.user, resolvers=resolvers)
```

This works because the caller always knows the entity type and which fields it's editing. The resolution knowledge stays in catalog.

### Bulk ingestion: orchestrator-driven

Management commands call `bulk_assert_claims()` (provenance), then explicitly call catalog resolution functions in the right order:

```python
# ingest_pindata.py — orchestrator manually sequences resolution
bulk_assert_claims(source=ipdb, pending=claims, ...)
resolve_all_entities(MachineModel, object_ids=changed_ids)
resolve_all_credits(model_ids=changed_ids)
resolve_all_themes(model_ids=changed_ids)
# ... etc
```

Again, catalog knowledge stays in catalog-aware code.

### The problem case: provenance-initiated mutations

One-click revert lives in provenance. It deactivates a claim, but then needs to:

1. Determine whether the entity is a MachineModel (uses `resolve_model`) or anything else (uses `resolve_entity`)
2. Look up which relationship resolver to call based on the claim's `field_name` (e.g., `theme_alias` needs `resolve_theme_aliases`)
3. Call `invalidate_all()` from catalog's cache module

This forces provenance to contain a dispatch table mapping claim namespaces to catalog resolver functions — hardcoded knowledge of every entity type and every relationship namespace. That's catalog's domain leaking into provenance.

## Why It Matters

Today it's revert. Tomorrow it could be:

- Claim expiration (auto-deactivate claims older than N days from low-priority sources)
- Moderation actions (admin deactivates a claim flagged for review)
- Source disabling (deactivate all claims from a source that's been marked unreliable)

Each of these is a provenance operation that needs catalog resolution afterward. Without a clean boundary, each one will need its own copy of the resolver dispatch table.

## The Shape of the Coupling

The coupling isn't symmetric. Provenance doesn't need to know _how_ resolution works — it just needs to say "claims changed for entity X, go figure it out." Catalog knows everything about resolution but has no way to offer that as a service.

What's missing is a **resolution trigger interface**: something provenance can call that says "this entity's claims changed" and catalog handles the rest — picking the right resolver, running relationship resolvers, invalidating caches.

The key inputs catalog needs:

- **Which entity** (model class + PK, or the instance itself)
- **Which fields changed** (optional — could just re-resolve everything, but targeted resolution is more efficient)

The key thing catalog should encapsulate:

- MachineModel vs everything else routing
- Which relationship resolvers to run for which field names
- Cache invalidation

## Constraints

- The bulk ingestion path resolves thousands of entities in optimized batches. Whatever interface we design must not force everything through a single-entity path. The batch path can remain orchestrator-driven — the problem is specifically single-entity mutations initiated by provenance.
- `resolve_model()` does things `resolve_entity()` doesn't (M2M relationships, media attachments, abbreviations). This asymmetry is real and needs to be preserved, not papered over.
- The relationship resolver dispatch depends on claim `field_name` values that are defined in `catalog/claims.py`. These are the canonical namespace strings (`theme_alias`, `gameplay_feature_parent`, etc.). Any registry-based approach would likely key on these.

## Current Workarounds

`execute_claims()` sidesteps the problem by making callers pass resolution details. This is fine for catalog-internal code (PATCH endpoints know their entity type). It doesn't work for provenance-initiated operations where the claim is fetched by PK and the entity type isn't known until runtime.

## Direction

### The resolution pipeline already exists — it just needs extracting

`execute_claims()` already does exactly what provenance needs: run relationship resolvers, run entity resolver, invalidate cache. The problem is that this pipeline is fused to claim creation. The fix is extracting the bottom half of `execute_claims()` into a standalone function, not building something new.

### `resolve_after_mutation(entity, field_names=None)`

A single function in `catalog.resolve` that provenance (or anything else) can call after mutating claims. Internally it:

1. Routes MachineModel to `resolve_model()` (which already handles all its own relationships)
2. Routes everything else to the appropriate relationship resolver(s) + `resolve_entity()`
3. Schedules cache invalidation via `transaction.on_commit(invalidate_all)`

The function performs resolution synchronously (inside whatever transaction the caller has open) but defers cache invalidation until after successful commit. This preserves current semantics: if resolution fails, the transaction rolls back and no stale cache is served. Callers don't need to know about this — they call one function, inside their own `transaction.atomic()` block.

`execute_claims()` itself becomes a thin wrapper: create claims, then call `resolve_after_mutation()`. Its existing `try/except` around `transaction.atomic()` continues to work unchanged — if resolution raises, the atomic block rolls back both the claims and the resolution, and `on_commit` never fires.

### Dispatch: auto-discover aliases, explicit dicts for the rest

`resolve_after_mutation()` needs to know which relationship resolver to run for a given `field_name`. The dispatch uses two strategies: auto-discovery where the pattern is universal and the type count is high, explicit dicts where the set is small and stable.

#### Auto-discovered: aliases

Walk `AliasBase.__subclasses__()` at import time. Each subclass has a FK to its parent model. Derive the claim field name as `{namespace}_alias` using `model._meta.verbose_name` with spaces replaced by underscores (Django auto-generates this from the class name: `GameplayFeature` → `"gameplay feature"` → `"gameplay_feature"`). Call `_resolve_aliases(model, field_name)` directly. This also auto-populates `LITERAL_SCHEMAS` (always `LiteralKey("alias_value", "alias")` for aliases) and replaces the hand-maintained `ALIAS_TYPES` list.

This covers 7 alias types today and scales to new ones with zero registration — defining the `AliasBase` subclass is sufficient.

#### Explicit dicts: everything else

Parents (2 entries) and simple M2Ms (3 entries) are small, stable sets that rarely grow — new hierarchies and new M2M relationships on MachineModel are structural additions, not something that happens with every new entity type. Introspection machinery (self-referential M2M detection, through-model field analysis) to save a handful of one-liners isn't worth the debugging cost. Keep these as readable, greppable dicts inside `resolve_after_mutation()`.

The full non-MachineModel dispatch:

```python
# Auto-discovered at import time from AliasBase subclasses
ALIAS_RESOLVERS: dict[str, tuple[type, str]] = _discover_alias_types()

# Explicit — small sets with stable membership
PARENT_RESOLVERS: dict[str, tuple[type, str]] = {
    "theme_parent": (Theme, "theme"),
    "gameplay_feature_parent": (GameplayFeature, "gameplay_feature"),
}
SIMPLE_M2M_RESOLVERS: dict[str, M2MFieldSpec] = {
    "theme": M2MFieldSpec("theme", "themes", Theme),
    "reward_type": M2MFieldSpec("reward_type", "reward_types", RewardType),
    "tag": M2MFieldSpec("tag", "tags", Tag),
}
# Custom resolvers — each accepts model_ids or entity_ids to scope
# to the mutated entity. resolve_after_mutation() passes {entity.pk}.
CUSTOM_RESOLVERS: dict[str, Callable[[set[int]], None]] = {
    "abbreviation": lambda ids: resolve_all_title_abbreviations(model_ids=ids),
    "corporate_entity_location": lambda ids: resolve_all_corporate_entity_locations(entity_ids=ids),
    "series_title": lambda ids: resolve_all_series_titles(model_ids=ids),
    "gameplay_feature": lambda ids: resolve_all_gameplay_features(model_ids=ids),
    "credit": lambda ids: resolve_all_credits(model_ids=ids),
}
```

Media attachments are handled by checking `isinstance(entity, MediaSupported)` when `field_name == "media_attachment"`. `resolve_media_attachments()` is already generic (takes content_type_id + entity_ids). Covers Manufacturer, Person, GameplayFeature, and MachineModel.

For MachineModel, `resolve_model()` already handles all relationships internally, so this dispatch only matters for non-MachineModel entities.

**Retiring old infrastructure:** Once `execute_claims()` calls `resolve_after_mutation()` internally, PATCH endpoints no longer pass resolvers. The per-entity wrapper functions (`resolve_theme_aliases()`, `resolve_theme_parents()`, etc.) become dead code and are removed. The hand-maintained `ALIAS_TYPES` list is replaced by auto-discovery. `M2M_FIELDS` stays as-is (it's already the right shape, just moves into the dispatch module).

### What this means for the revert plan

The revert plan's step 6 (determine `resolve_fn`) and step 7 (determine relationship resolvers) collapse into a single call: `resolve_after_mutation(entity, field_names=[target.field_name])`. The `isinstance` routing, resolver lookup, and cache invalidation all move inside that function.

### Decisions

- **Simple function, not events.** Direct call. Events add indirection and debugging cost with no second subscriber to justify them.
- **Cache invalidation is internal, via `on_commit`.** The whole point is "call one thing." The caller doesn't manage cache invalidation. But invalidation is deferred to after commit via `transaction.on_commit()`, so it never fires if the transaction rolls back.
- **Bulk path stays separate.** Bulk ingestion resolves thousands of entities in optimized batches with explicit sequencing. Forcing it through a single-entity interface would be a performance regression. The orchestrator-driven pattern is correct for bulk; this interface is for single-entity mutations initiated outside catalog.
