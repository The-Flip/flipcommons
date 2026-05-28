# Model-Driven Delete Page

## Context

This work is an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior as metadata, consume it generically from shared infrastructure.

It is the frontend delete-page slice of the existing delete-preview / delete / restore wire shape. This doc intentionally depends only on stable route shape and catalog metadata; it does not assume a chosen model-driven API registrar.

Today every catalog model that supports soft-delete has its own `frontend/src/routes/{plural}/[slug]/delete/+page@.svelte` — 19 of them at time of writing (cabinets, corporate-entities, credit-roles, display-subtypes, display-types, franchises, game-formats, gameplay-features, manufacturers, models, people, reward-types, series, systems, tags, technology-generations, technology-subgenerations, themes, titles), plus `locations` once Location CRUD lands. Each is structurally identical: read `data.preview`, build a `BlockedState` from `preview.blocked_by`, build an `impact` object, render `<DeletePage>`. The shared `DeletePage.svelte` component already does the heavy lifting; the wrappers are pure glue + per-entity copy.

The shared infra is already in place. [`DeletePage.svelte`](../../../frontend/src/lib/components/DeletePage.svelte) is one component. [`createDeleteSubmitter`](../../../frontend/src/lib/delete-flow.ts) is one factory keyed by entity collection. The wire shape (`/api/{collection}/{public_id}/delete-preview/` and `/api/{collection}/{public_id}/delete/`) is identical across every entity. What's missing is a metadata registry that lets a single dynamic route resolve "given this entity_type, what label / copy / redirect should I use?" without 19 hand-rolled wrappers.

This plan replaces all 19 wrappers (and `+page.server.ts` + `*-delete.ts` siblings) with a single dynamic delete route driven by extended `catalog-meta`.

## Family of plans (Soft-Delete Metadata)

This is one of three coordinated plans that put soft-delete-related metadata on `LifecycleStatusModel` and consume it generically. Each ships independently along a different layer:

- [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md) — **data layer.** Cascade and block declarations consumed by the soft-delete planner (`apps/catalog/api/soft_delete.py`).
- [ModelDrivenDeleteRoutes.md](ModelDrivenDeleteRoutes.md) — **API layer.** Route registration for the delete-preview / delete / restore trio, with `__subclasses__()`-driven discovery.
- **[ModelDrivenDeletePage.md](ModelDrivenDeletePage.md) (this doc) — frontend layer.** Per-entity copy strings exported via `CATALOG_META`, consumed by a single dynamic delete-page route.

The three docs share a base class but consume different things and ship in any order.

### Prefix convention

Two prefixes are intentional, not drift:

- `soft_delete_*` — data-layer / DB-mechanism declarations: how the cascade walks, what blocks the soft-delete write at the model layer. Lives in [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md).
- `delete_*` — API and presentation declarations: which routes to expose, what copy to render, where to redirect, what FK ties to the parent for breadcrumb / redirect. Lives in [ModelDrivenDeleteRoutes.md](ModelDrivenDeleteRoutes.md) and this doc.

When in doubt, ask: is this a fact about the soft-delete cascade machinery, or a fact about the API/presentation delete experience? The answer picks the prefix.

## Backend prerequisites

This plan assumes a few backend-side preview-response extensions. They are listed here (rather than in [ModelDrivenDeleteRoutes.md](ModelDrivenDeleteRoutes.md), which is intentionally a pure refactor) because they're motivated by frontend needs and aren't required by the API-layer route consolidation:

- **Tagged-union `blocked` shape.** Add `blocked_message: string | null` to the delete-preview response. When set, the frontend renders `kind: 'message'` in `BlockedState`; otherwise it falls back to `blocked_by` and renders `kind: 'referrers'`. Person uses this for the "credited on N active machines" path.
- **Parent metadata on preview.** Surface `preview.parent: { name, public_id, parent_entity_type } | null`. Most entities already carry a `parent` field where applicable; this adds `parent_entity_type` so the dynamic route can build the redirect URL into the parent's collection without the frontend hardcoding `manufacturer` for `corporate-entity`, `title` for `model`, etc.
- **`active_credit_count` (Person)** and any equivalent per-entity counts — backend computes; frontend just reads.

These are additive, so they can land independently of [ModelDrivenDeleteRoutes.md](ModelDrivenDeleteRoutes.md). They're prerequisites for this plan, not prerequisites for the API-layer consolidation.

## The contracts

Extend `CATALOG_META` (generated from the backend by `export_catalog_meta`) with delete-specific metadata per entity:

```ts
type DeleteMeta = {
  blocked_lead: string; // "This theme can't be deleted because active records still point at it:"
  referrer_hint_template: string; // "references this theme via {relation}" — `{relation}` substituted at render time
  blocked_footer: string | null; // "Resolve these references, then try again." or null
  impact_singular: string; // "this theme"
  restore_note: string; // "You can undo this from the toast that appears on the themes page, …"
};

type CatalogEntry = {
  entity_type: string;
  entity_type_plural: string;
  label: string; // existing
  label_plural: string; // existing
  delete: DeleteMeta; // new
};
```

The backend exporter (`apps/catalog/management/commands/export_catalog_meta.py`) reads each model's existing `verbose_name` / `verbose_name_plural` for `label` and a new `Meta`-adjacent contract for delete copy:

```python
class Theme(...):
    class Meta:
        verbose_name = "theme"
        verbose_name_plural = "themes"
        # New ClassVar on LifecycleStatusModel (default-derived, override-able):
    delete_blocked_lead: ClassVar[str] = ...   # default: f"This {verbose_name} can't be deleted because active records still point at it:"
    delete_referrer_hint_template: ClassVar[str] = ...  # default: f"references this {verbose_name} via {{relation}}"
```

For the 90%+ of entities that just want the boilerplate copy with their `verbose_name` substituted in, the defaults on `LifecycleStatusModel` produce the right strings without a per-model declaration. Only entities with non-standard copy (Person's "credited on N machines", Location's "across this subtree", CorporateEntity's "via the manufacturer") override.

## Generic referrer-href resolution

The current wrappers all hand-roll `renderReferrerHref`. Most return `null` unconditionally (a missed opportunity — `BlockingReferrer` carries `entity_type` and `slug`). [CorporateEntity](../../../frontend/src/routes/corporate-entities/[slug]/delete/+page@.svelte) special-cases `entity_type === 'model'`. There's no real reason this is per-entity.

The dynamic route gets a single shared `renderReferrerHref`:

```ts
function renderReferrerHref(r: BlockingReferrer): string | null {
  if (!r.slug) return null;
  const meta = CATALOG_META[r.entity_type];
  if (!meta) return null;
  return `/${meta.entity_type_plural}/${r.slug}`;
}
```

This is strictly an improvement over the status quo — most wrappers' `() => null` becomes a working link, and CorporateEntity's special case becomes the default behavior.

## The dynamic route

Replace all 19 per-entity delete trees with a single route under `frontend/src/routes/[entity_plural]/[...public_id]/delete/`:

- `+page.server.ts` — load `params.entity_plural` + `params.public_id`, resolve to a `CATALOG_META` entry by matching `entity_type_plural` (the URL segment carries the plural form like `gameplay-features`, but `CATALOG_META` is keyed by singular `entity_type` like `gameplay-feature`). 404 if no match. Fetch the delete-preview via `client.GET('/api/{collection}/{public_id}/delete-preview/')`, return `{ preview, meta, public_id }`.
- `+page@.svelte` — build `BlockedState` from `preview.blocked_by` using `meta.delete.blocked_lead` / `referrer_hint_template` / `blocked_footer`, build `impact` from `meta.delete.impact_singular` + `pluralize(preview.changeset_count, 'change set')` + `meta.delete.restore_note`, render `<DeletePage>` with `submit={createDeleteSubmitter(meta.entity_type_plural)}`, `redirectAfterDelete={'/' + meta.entity_type_plural}`, `cancelHref={'/' + meta.entity_type_plural + '/' + public_id}`, `editHistoryHref={cancelHref + '/edit-history'}`.

The plural-to-singular lookup wants either an indexed helper (`getCatalogMetaByPlural(plural)`) co-located with `CATALOG_META`, or a parallel index emitted by `export_catalog_meta`. Pick whichever feels lighter; the `Object.values(CATALOG_META).find(...)` form is fine for ~20 entries but the helper makes the route's intent obvious.

`[...public_id]` (rest segment) makes the route work for both single-segment slugs (themes/`abc`) and multi-segment public IDs (locations/`usa/il/chicago`) without a second route.

The dynamic route's `[entity_plural]` segment shadows static entity routes by file precedence — SvelteKit resolves `/themes/abc/delete` to the static `themes/[slug]/delete/` first if it exists. The per-entity wrappers must be deleted in the same PR that adds the dynamic route, otherwise the dynamic route is dead code. After deletion, every entity's `…/{public_id}/delete` URL routes to the single dynamic page.

## Per-entity escape hatches

Three entities deviate from the boilerplate today. Each gets a focused hook rather than reverting that entity to a hand-rolled wrapper:

- **Person** uses `kind: 'message'` blocked state when `preview.active_credit_count > 0`, replacing the referrer list with a single sentence. Handled by extending `delete-preview` to a tagged-union response: when the backend reports `active_credit_count > 0`, the preview body carries a top-level `blocked_message: string` that the frontend prefers over `blocked_by`. Person's `active_credit_count` formatting moves to a backend-rendered string ("Joe Smith is credited on 3 active machines. …") so the frontend doesn't need entity-specific message-building. Net: the frontend `BlockedState` resolution becomes "if `preview.blocked_message`, render `kind: 'message'`; else if `preview.blocked_by`, render `kind: 'referrers'`; else null."

- **CorporateEntity** sets `parentBreadcrumb` and a parent-aware `redirectAfterDelete` (back to the manufacturer's page when there's a parent). Handled by surfacing the parent on the existing preview schema as `preview.parent: { name, public_id, parent_entity_type } | null` (already present for CE) and teaching the dynamic route to consume it: when `preview.parent` is set, build `parentBreadcrumb` and override `redirectAfterDelete` to point at the parent. The `parent_entity_type` field tells the route which collection to redirect into. Generalizes for free to any future entity that wants parent-aware delete UX.

- **Location** wants subtree-cascade language ("this location and all descendants") and a child→parent redirect (delete `usa/il/chicago` → land on `usa/il`). The parent-aware redirect drops out of the same `preview.parent` mechanism. The cascade language rides on `meta.delete.impact_singular` being declared as `"this location and all descendants"` (i.e. it's already a per-entity string, just declared on the model rather than hardcoded in a wrapper).

After these three hooks, no entity needs a hand-rolled wrapper.

## Migration

Single PR:

1. Add `delete_blocked_lead`, `delete_referrer_hint_template`, `delete_blocked_footer`, `delete_impact_singular`, `delete_restore_note` ClassVars to `LifecycleStatusModel` with defaults derived from `Meta.verbose_name` / `verbose_name_plural`. Override on Person, CorporateEntity, Location where they differ.
2. Extend `export_catalog_meta` to emit the new `delete` block. Regenerate `frontend/src/lib/models/model-meta.ts` via `make codegen`.
3. Add `frontend/src/routes/[entity_plural]/[...public_id]/delete/{+page.server.ts,+page@.svelte}` driven by the registry.
4. Delete the 19 per-entity delete trees (`+page@.svelte`, `+page.server.ts`, `*-delete.ts`) and their tests. Keep `createDeleteSubmitter` — it's still the right factory; the dynamic route just calls it once with `meta.entity_type_plural` instead of each wrapper baking the collection in at module scope.
5. Add `tests/routes/dynamic-delete.test.ts` (DOM test, same harness as the existing `DeletePage.dom.test.ts`) covering: registry-driven copy substitution, `referrer_hint_template`'s `{relation}` substitution, `parentBreadcrumb` from `preview.parent`, parent-aware `redirectAfterDelete`, `blocked_message` (Person path), unknown `entity_plural` → 404.

The PR is large by line count (19 trees deleted + 1 added + 1 backend file + 1 generated registry update) but the diff is mostly deletions. The new code is the dynamic route (~100 lines) and 5 ClassVar declarations on `LifecycleStatusModel`.

## Tests

Backend:

- `export_catalog_meta` emits `delete` block per entity with default-derived strings for plain models and overridden strings for Person / CorporateEntity / Location.
- Person delete-preview returns `blocked_message` when `active_credit_count > 0` and `blocked_by` otherwise.
- CorporateEntity delete-preview surfaces `preview.parent` with `parent_entity_type='manufacturer'` when applicable.

Frontend:

- Dynamic delete route resolves `params.entity_plural` to a `CATALOG_META` entry via `entity_type_plural`, 404s on unknown.
- Substitutes `{relation}` in `referrer_hint_template`.
- Renders `parentBreadcrumb` when `preview.parent` is set; redirects to parent collection on success.
- Renders `kind: 'message'` blocked state when `preview.blocked_message` is set.
- `referrerHref` builds correct URLs from `BlockingReferrer.entity_type` + `slug` for every entity in `CATALOG_META`.

## Out of Scope

- Generalizing the same registry to drive edit-history and sources subroutes. Those already share generic loaders ([`provenance-loaders.ts`](../../../frontend/src/lib/provenance-loaders.ts)) but still have 19 per-entity `+page.server.ts` files that just forward `event.params.slug`. Same shape as the delete consolidation, but each follow-up gets its own focused PR — combining them forces a reviewer to evaluate three independent unifications at once.
- Generalizing the per-entity create routes. Create has more genuine variation (form fields, validation, redirect target depends on parent) and isn't ripe for one dynamic route yet.
- Removing the per-entity `*-delete.ts` shims if any of them carry entity-specific submission logic (none do today, but verify before deleting). If any does, leave that one wrapper in place and unify the rest.
- Driving the per-entity ChangeSetAction copy ("deleted theme X" toast text) from the registry. Toasts already format generically; no work needed.
