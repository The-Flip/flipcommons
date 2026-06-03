# Route Metadata and Walking

Plan for the shared classification machinery — `frontend/src/lib/route-metadata.server.ts` — that answers "is this route indexable?" for sitemap, robots, noindex meta, canonical, SSR enforcement and title/description enforcement. Those consumers live downstream and are described in [`SearchEngines.md`](SearchEngines.md).

## Status: ✅ Implemented

This plan has been implemented.

## Key design element

The headline design choice: **derive indexability from the catalog entity registry where possible, declare it per-route only for the small set of routes that can't be derived.** This follows the project's [model-driven metadata](../model_driven_metadata/ModelDrivenMetadata.md) discipline — the catalog model is the source of truth, not parallel per-route declarations.

## Why

Two facts about the route tree make per-route co-located classification the wrong shape:

1. **Most routes are catalog routes.** The entity registry has 20 entries today. Each one has a detail route, a listing route and edit / delete / edit-history / sources / new subroutes. That's ~140 catalog routes vs. ~14 non-catalog ones. Their indexability is a class fact, not a per-route fact: every detail page is indexable, every edit subroute isn't. Co-locating an export on each one would be ~140 mechanical declarations that all say the same thing — and adding a new catalog entity would mean remembering to add five more. That's exactly the "code expansion instead of declaration" smell [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md) is fighting.
2. **A small set of routes are outside the catalog convention.** `/`, `/about`, `/(legal)/*`, `/login`, `/signup`, `/verify-email`, `/auth/error`, `/search`, `/style-lab`, `/api-docs`, `/kiosk/*`, `/users/[username]`, `/_sentry_test`. Their indexability isn't derivable from any registry — it's a per-route product decision. (`/__health` is a `+server.ts` endpoint, not a page — `allRoutes()` doesn't enumerate it and the classifier never sees it.)

The right split: catalog routes inherit class-level answers from the existing entity registry ([`entity-meta.ts`](frontend/src/lib/entities/entity-meta.ts)); the rest get short hand-maintained allowlists. The walker exists mainly to enforce "every route fits into exactly one bucket" — catching anything that slips through unclassified.

The auth-gate check the walker needs anyway (gated routes aren't indexable) covers `/admin/*` and `/kiosk/edit/*` for free.

## Invariants

The design MUST satisfy these two properties:

1. **Adding a new catalog entity requires zero SEO declarations.** Once the entity ships as a catalog entity (in `CATALOG_ENTITY_KEYS`), detail / listing / edit-history / sources / edit / new / delete routes all classify correctly without any human-authored per-route metadata. Any design that requires the contributor to remember to add an SEO declaration alongside their new entity violates this invariant.
2. **Adding a non-catalog route forces an explicit classification decision.** The walker test fails until the route appears in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`, `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS`, or under a non-catalog auth-gated layout (today `/admin/*` and `/kiosk/edit/*`). There is no silent default — an unclassified route is a test failure, not an "implicitly included" or "implicitly excluded" route.

The first invariant comes from the [model-driven metadata](../model_driven_metadata/ModelDrivenMetadata.md) discipline: parallel hand-maintained per-route declarations are exactly the drift surface model-driven design eliminates. The second invariant comes from the SEO consequences of "wrong default": a route silently included that shouldn't be leaks into search indexes and is expensive to remove (every major engine caches removed pages for months); a route silently excluded that shouldn't be costs traffic invisibly. Both directions of failure are slow to detect; forcing the decision at PR time is cheap by comparison.

## The classification

Catalog routes are classified by **URL pattern** against the `entity_type_plural` values of the catalog entities — `CATALOG_ENTITY_KEYS`, the `CatalogEntityKey` subset, **not** the broader `ENTITY_META`. (`ENTITY_META` is the full linkable-entity registry; once a non-catalog entity such as `user` joins it, that entity must _not_ pick up the catalog route patterns — hence classification walks the catalog subset.) Auth-gated areas outside the catalog (`/admin/*` and `/kiosk/edit/*` today) are classified by **import scan**. Everything else comes from short hand-maintained allowlists.

| Bucket                       | How it's recognized                                                                                                                                               | Indexable?                                                                                                                                                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Catalog: listing**         | `/{plural}`                                                                                                                                                       | Yes — listing pages are SSR and emit metadata/JSON-LD, so they are indexable and included in the sitemap. Filtered/paginated variants canonicalize back to the bare listing. See [`SearchEngines.md`](SearchEngines.md). |
| **Catalog: detail**          | `/{plural}/[public-id]`                                                                                                                                           | Yes                                                                                                                                                                                                                      |
| **Catalog: edit-history**    | `/{plural}/[public-id]/edit-history`                                                                                                                              | Yes                                                                                                                                                                                                                      |
| **Catalog: sources**         | `/{plural}/[public-id]/sources`                                                                                                                                   | Yes                                                                                                                                                                                                                      |
| **Catalog: edit**            | `/{plural}/[public-id]/edit` (with optional `/[section]`). Gated by convention (`catalog.edit`).                                                                  | No                                                                                                                                                                                                                       |
| **Catalog: new**             | `/{plural}/new`, `/{plural}/[public-id]/new` and nested-create patterns like `/{plural}/[public-id]/{nested-plural}/new`. Gated by convention (`catalog.create`). | No                                                                                                                                                                                                                       |
| **Catalog: delete**          | `/{plural}/[public-id]/delete`. Gated by convention (`catalog.delete`) via the shared `loadDeletePreview` helper.                                                 | No                                                                                                                                                                                                                       |
| **Auth-gated (non-catalog)** | Any ancestor `+layout.server.ts` imports `$lib/require-capability.server`. Today: `/admin/*`, `/kiosk/edit/*`.                                                    | No                                                                                                                                                                                                                       |
| **Listed indexable**         | Route ID appears in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`                                                                                                           | Yes                                                                                                                                                                                                                      |
| **Listed non-indexable**     | Route ID appears in `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS`                                                                                                       | No                                                                                                                                                                                                                       |

`{plural}` matches the `entity_type_plural` of any catalog entity (`CATALOG_ENTITY_KEYS`). `[public-id]` is the entity's public identifier and may contain slashes — most entities use a single path segment (`/titles/medieval-madness`), but Location uses a multi-segment hierarchical path (`/locations/usa/il/chicago/logan-arcade`). The matcher accepts both forms. New catalog entities light up every row automatically as soon as they appear in `CATALOG_ENTITY_KEYS` — this is how Invariant 1 is satisfied. The walker-test "every route is classified" rule is how Invariant 2 is enforced.

`/models/[slug]` classifies as `catalog-detail` (indexable) like every other detail route; the existing 301 redirect on single-model Titles handles the Title↔Model duplicate at request time, so the walker doesn't need to know about the collapse rule.

### Nested listings under a catalog detail

A handful of routes are shaped like `/{plural}/[public-id]/{nested-plural}` — a page that lists entities related to a parent. Today only `/manufacturers/[slug]/systems` exists as a real page (has its own `+page.svelte`, SSR via the `[slug]/+layout.ts` ancestor). `/titles/[slug]/models` and `/manufacturers/[slug]/corporate-entities` are directory-only — they exist solely to host `/new` underneath — so they have no page file (neither `+page.svelte` nor `+page@*.svelte`) and don't appear in `allRoutes()`.

With N=1, we don't introduce a `catalog-nested-listing` class. A regex for that pattern would have to carve out `edit` / `edit-history` / `sources` / `delete` / `new` as exclusions — more machinery than one route warrants. Instead, `/manufacturers/[slug]/systems` lives in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS` as a deliberate per-route product decision. Revisit when a second nested listing ships.

## The module

```ts
// frontend/src/lib/route-metadata.server.ts
import { CATALOG_ENTITY_KEYS, ENTITY_META, type CatalogEntityKey } from "$lib/entities/entity-meta";

// Route IDs (SvelteKit page.route.id form — groups like (legal) and params
// like [username] preserved). NOT URLs — /(legal)/privacy, not /privacy.
// `satisfies readonly RouteId[]` pins entries to SvelteKit's generated
// RouteId union, catching typos and stale entries at compile time.
export const SEARCH_ENGINE_INDEXABLE_ROUTE_IDS = [
  "/",
  "/about",
  "/about/people",
  "/(legal)/privacy",
  "/(legal)/terms",
  "/(legal)/licensing",
  "/manufacturers/[slug]/systems",
] as const satisfies readonly RouteId[];

// Route IDs (SvelteKit page.route.id form — groups and params preserved).
// NOT URLs — /users/[username], not /users/moses.
export const SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS = [
  "/login",
  "/signup",
  "/verify-email",
  "/auth/error",
  "/search",
  "/style-lab",
  "/api-docs",
  // Low search value while user pages are an activity stream rather than a
  // stable profile. Revisit if user pages grow real profile content.
  "/users/[username]",
  "/changesets",
  "/review",
  "/kiosk",
  "/_sentry_test",
] as const satisfies readonly RouteId[];

export type RouteClass =
  | { kind: "catalog-listing"; entity: CatalogEntityKey }
  | { kind: "catalog-detail"; entity: CatalogEntityKey }
  | { kind: "catalog-edit-history"; entity: CatalogEntityKey }
  | { kind: "catalog-sources"; entity: CatalogEntityKey }
  | { kind: "catalog-edit"; entity: CatalogEntityKey }
  | { kind: "catalog-new"; entity: CatalogEntityKey }
  | { kind: "catalog-delete"; entity: CatalogEntityKey }
  | { kind: "auth-gated" } // non-catalog, via import scan
  | { kind: "listed-indexable" }
  | { kind: "listed-non-indexable" }
  | { kind: "unclassified" };

export function classifyRoute(id: RouteId): RouteClass {
  // 1. Try catalog patterns against every CATALOG_ENTITY_KEYS entity's entity_type_plural
  // 2. Try non-catalog auth-gate (ancestor +layout.server.ts imports $lib/require-capability.server)
  // 3. Try the two listed allowlists
  // 4. Fall through to 'unclassified'
}

export function isSearchEngineIndexable(id: RouteId): boolean {
  const c = classifyRoute(id);
  switch (c.kind) {
    case "catalog-listing":
    case "catalog-detail":
    case "catalog-edit-history":
    case "catalog-sources":
    case "listed-indexable":
      return true;
    case "catalog-edit":
    case "catalog-new":
    case "catalog-delete":
    case "auth-gated":
    case "listed-non-indexable":
      return false;
    case "unclassified":
      // Throw, don't soft-fail. The every-route-classified vitest test is
      // the primary gate (run in CI before deploy); on the rare slip-through,
      // a loud 500 on the affected route is the right failure mode. A silent
      // `return false` with a `console.error` is the worst of both worlds:
      // pages that should be indexed silently aren't, and the log line in a
      // server stream rarely gets read until traffic drops.
      throw new Error(`Route ${id} is unclassified. Add it to a catalog convention, an auth-gated layout, or one of the SEARCH_ENGINE_*_ROUTE_IDS allowlists.`);
  }
}

// Enumerates page-bearing route IDs — every route with a +page.svelte OR
// +page@*.svelte (reset-layout form, used by every catalog /delete page and
// the nested-create pages). A naïve `+page.svelte` glob silently excludes
// 22 of 157 page routes. +server.ts endpoints are excluded: non-HTML
// responses, no meta-tag surface. Directory-only routes (e.g.
// /titles/[slug]/models, which exists solely to host /new underneath) are
// also excluded since they have no +page.svelte and SvelteKit never serves
// them as a page.
export function allRoutes(): RouteId[] {
  /* import.meta.glob('/src/routes/**/+page*.svelte') — then strip the
     @-suffix from the filename to recover the route ID. */
}
```

Public surface: `classifyRoute`, `isSearchEngineIndexable`, `allRoutes`, the two `SEARCH_ENGINE_*_ROUTE_IDS` constants (consumed by the sitemap), and the `RouteClass` / `CatalogRouteClass` types plus the `isCatalogRoute` type guard (consumed by the entity-meta and convention tests). Pattern-match helpers and the auth-gate import-scan stay file-private.

Catalog pattern-matching is straightforward: walk `CATALOG_ENTITY_KEYS`, build a regex per catalog entity's `entity_type_plural` (looked up via `ENTITY_META[key]`), match against `routeId`. The `[public-id]` slot realizes as `[slug]` at the SvelteKit level for most entities and as `[...path]` for Location; the matcher handles both. Nested-create routes (e.g. `/titles/[public-id]/models/new`, `/manufacturers/[public-id]/corporate-entities/new`) are recognized as `catalog-new` for the inner entity.

Non-catalog auth-gate detection: scan every ancestor `+layout.server.ts` for a `$lib/require-capability.server` import. The scan matches `/admin/+layout.server.ts`, `/kiosk/edit/+layout.server.ts`, and every `/{plural}/[slug]/edit/+layout.server.ts`. The catalog-edit hits are redundant with the catalog-pattern bucket: classification tries catalog patterns first, so catalog-edit routes are claimed before this scan ever fires. After catalog-pattern matching, the routes the scan effectively catches are `/admin/*` and `/kiosk/edit/*` (and `/kiosk/edit` itself — see prefix-match note below). A new non-catalog gated area (say `/ops/*`) is covered by the same rule — no allowlist needed.

## Enforcing the convention

The catalog classification trusts that `catalog-edit` / `catalog-new` / `catalog-delete` routes are actually gated. That trust needs its own enforcement, separate from the walker:

A small test (lives next to the walker) asserts the gate is in place for every catalog entity:

- For each catalog key in `CATALOG_ENTITY_KEYS` (its `ENTITY_META[key].entity_type_plural`):
  - The `edit` route's `+layout.server.ts` imports `$lib/require-capability.server` and calls `requireCapability({ activity: 'catalog.edit', ... })`.
  - The `new` route's `+page.server.ts` (and any nested-create page) imports `$lib/require-capability.server` and uses `activity: 'catalog.create'`.
  - The `delete` route's `+page.server.ts` imports `$lib/delete-preview-loader.server` (the helper that calls `requireCapability({ activity: 'catalog.delete' })`).

Cheap text-match scan. Fails loudly if someone adds a catalog entity without wiring its standard auth gates. The walker stays simple because gate-presence is enforced in a separate, narrowly-scoped test rather than encoded as walker knowledge.

## Performance

`isSearchEngineIndexable(routeId)` runs on every SSR request that injects a noindex meta tag, so per-request cost matters. Every lookup is O(small) and touches no filesystem:

- **Catalog pattern match.** Regex against a small precomputed set of patterns derived from `CATALOG_ENTITY_KEYS` at module load.
- **Non-catalog auth-gate.** A precomputed set of gated route-ID prefixes: `/admin`, `/kiosk/edit`, and every `/{plural}/[slug]/edit` (the catalog-edit ones are dead code in practice since catalog-pattern matching runs first, but the set has them). Prefixes are in SvelteKit pattern form (literal `[slug]` / `[...path]` brackets) — same shape as `page.route.id`, so no URL normalization needed. The match is `routeId === prefix || routeId.startsWith(prefix + '/')`, **not** a plain `startsWith(prefix + '/')` — the latter misses the layout's own page (e.g. the route ID for `/kiosk/edit/+page.svelte` is `/kiosk/edit`, with no trailing slash). Built via `import.meta.glob('/src/routes/**/+layout.server.ts', { eager: true, query: '?raw', import: 'default' })` — Vite resolves this at **build time** and bakes each matched layout's source into the SSR bundle as a top-level string-literal `const`. At module load, one pass over the matched strings substring-checks for `from '$lib/require-capability.server'` and computes the prefix set. No filesystem I/O at runtime. Do NOT implement this with `fs.readFile` / `fs.readdir` at module load — that pays real I/O on every cold worker start and breaks when the SSR bundle is deployed without the source tree.
- **Listed allowlist.** `Set.has(routeId)` against the two `SEARCH_ENGINE_*_ROUTE_IDS` constants.

The `import.meta.glob('/src/routes/**/+*')` walk is resolved by Vite at **build time**, not request time. It exists only to enumerate the route tree for:

- The vitest tests (every-route-classified, indexable-routes-are-SSR, anchor sanity, catalog-auth-convention).
- The sitemap generator at build time (or whenever it regenerates).

SvelteKit provides `page.route.id` already in pattern form (`/titles/[slug]`, not `/titles/medieval-madness`), so there's no URL parsing at request time either — the input string is already what the walker expects.

## The test (`route-metadata.test.ts`)

The walker exists to enforce three things:

1. **Every route is classified.** Walk `allRoutes()`, call `classifyRoute()` on each and assert no `unclassified` results. New routes fail until they're either gated, follow a catalog convention or appear in one of the two listed allowlists.
2. **Every indexable route is SSR-enabled.** Walk `allRoutes()`, filter to `isSearchEngineIndexable(routeId) === true`, and for each one assert the route resolves to `ssr === true` after walking its config ancestor chain. SvelteKit's resolution rule: walk from leaf up through ancestors, take the first `export const ssr = X` declaration found in any of `+page.ts` / `+page.js` / `+page.server.ts` / `+layout.ts` / `+layout.js` / `+layout.server.ts` at that level, default to `true` if none. (The `.server.ts` variants matter: catalog `[slug]/edit/+layout.server.ts` is exactly where `ssr = false` lives today.) Same raw-source trick as the auth-gate scan — bake source into the bundle at build time via `import.meta.glob('?raw')`, scan for `export const ssr = (true|false)` with a regex. Fails loudly if someone flips `ssr = false` on a layout that contains an indexable page, or adds a new indexable route without giving it SSR.
3. **Anchor sanity.** A small table of stable route IDs resolves to the expected `RouteClass` and `isSearchEngineIndexable()` values. Inputs are in **route-pattern form** — the same shape `page.route.id` has at runtime and the same shape `classifyRoute()` takes — not resolved URLs. That keeps the test exercising the real input shape, lets the `RouteId` type catch typos and renames at compile time, and avoids reimplementing SvelteKit's matcher (which would be wrong on `[...path]`):

   ```ts
   // Anchors use route-pattern form (page.route.id), not resolved URLs.
   const ANCHORS: Array<[RouteId, RouteClass["kind"], boolean]> = [
     ["/", "listed-indexable", true],
     ["/about", "listed-indexable", true],
     ["/titles", "catalog-listing", true],
     ["/titles/[slug]", "catalog-detail", true],
     ["/titles/[slug]/edit-history", "catalog-edit-history", true],
     ["/titles/[slug]/edit", "catalog-edit", false],
     ["/locations/[...path]", "catalog-detail", true],
     ["/login", "listed-non-indexable", false],
     ["/admin/dashboard", "auth-gated", false],
     // Pins the prefix-match off-by-one: /kiosk/edit is the layout's own
     // page (no trailing slash), not just a parent of /kiosk/edit/[id].
     ["/kiosk/edit", "auth-gated", false],
   ];
   ```

   Defends against "walker returned nothing, so all assertions trivially pass." Self-documenting; a magic-number count threshold would catch the same case less precisely and would rot on intentional consolidation.

4. **The two allowlists are disjoint.** A short assertion that no route ID appears in both `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS` and `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS`. Two separate `as const` arrays are more readable than a single map, but TypeScript can't catch double-entry at compile time; this test does.

That's the whole walker-test surface. The separate `catalog-auth-convention.test.ts` (see [Enforcing the convention](#enforcing-the-convention)) covers gate-presence; the two tests together cover both "every route is classified" and "every convention-gated catalog route actually has its gate."

## Refactor: fold the existing route walker into this module

[`frontend/src/lib/entities/entity-meta.test.ts`](frontend/src/lib/entities/entity-meta.test.ts) already walks the route tree via `import.meta.glob('/src/routes/**/+*')` to enforce that every catalog key (`CATALOG_ENTITY_KEYS`) has detail and edit-history / sources subroutes. The `route-metadata` walker needs the same enumeration. Two changes:

- Move the `import.meta.glob` walk into `route-metadata.server.ts`'s `allRoutes()`.
- Have `entity-meta.test.ts` consume `allRoutes()` + `classifyRoute()` instead of doing its own glob + regex. The `ROUTE_DIR_TO_KEY` / `UNMAPPED_ROUTE_DIRS` / `DEFERRED_KEYS` structure becomes redundant: catalog membership now comes from `CATALOG_ENTITY_KEYS` and the route-class match, not a parallel hand-maintained map.

The module is suffixed `.server.ts` because it uses `import.meta.glob('/src/routes/**/+layout.server.ts', { eager: true, query: '?raw' })` to scan auth-gate imports. Vite inlines each matched file's source as a string literal at build time, and SvelteKit's normal "you can't import a `.server.ts` from client code" check doesn't apply to `?raw` (it's a string, not a module). Without the `.server` suffix on this module, any client-side importer would ship every `+layout.server.ts` and `+page.server.ts` source string into the browser bundle. Downstream consumers (noindex meta injection, canonical URL helper, etc.) should call `isSearchEngineIndexable()` from a `.server.ts` site (a server `handle` hook, a server load) — not from a `.svelte` file.

Out of scope — don't touch:

- [`frontend/src/lib/focus-mode.ts`](frontend/src/lib/focus-mode.ts) (`MINIMAL_SHELL_EXACT_PATHS`, `FOCUS_EXACT_PATHS`) classifies routes by UI chrome, a different axis. Some paths overlap (`/signup`, `/auth/error`, `/kiosk`, `*/edit`) but binding two axes together creates a future "they diverged" headache. Revisit only if they actually drift.
- [`frontend/src/lib/frontDoors.ts`](frontend/src/lib/frontDoors.ts) is a UI-shell concern; unrelated.

## What this enables downstream

Full consumer list lives in [`SearchEngines.md`](SearchEngines.md); short version:

- **`robots.txt`** — see [`Robots.md`](Robots.md). Server-endpoint disallows, mostly orthogonal to route classification.
- **`sitemap.xml`** — see [`Sitemap.md`](Sitemap.md). Enumerates per-entity URLs from the catalog entities (`CATALOG_ENTITY_KEYS`) + entity data: the detail page plus an `/edit-history` and `/sources` URL per entity. Adds the entries from `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`. The walker's `isSearchEngineIndexable()` is the filter for any include/exclude question.
- **`<meta name="robots" content="noindex" />`** — see [`NoindexMeta.md`](NoindexMeta.md). Injected by a `handle` hook (`hooks.server.ts`) via `transformPageChunk`, driven by `isSearchEngineIndexable(event.route.id)`. The hook also sets the `X-Robots-Tag` response header.
- **Canonical URL** — see [`CanonicalUrl.md`](CanonicalUrl.md). Catalog detail derives the canonical from the entity's `link_url_pattern`; listed indexable routes derive it from the route ID.
- **Title/description presence test** — every indexable route declares a meaningful `<title>` and `<meta name="description">`. Catalog detail derives both from entity data; listed indexable routes declare them in the page.

(The SSR-enforcement test ships in `route-metadata.test.ts` itself — see "The test" above — not as a downstream consumer.)

## Implementation order

1. Write `frontend/src/lib/route-metadata.server.ts`: types, `allRoutes()`, `classifyRoute()` (catalog pattern-match + non-catalog import-scan + listed allowlists), `isSearchEngineIndexable()`.
2. Add `route-metadata.test.ts`: every-route-classified + anchor sanity + disjoint allowlists + SSR-enforcement (every indexable route resolves to `ssr === true` after walking the config-file ancestor chain). Expect the unclassified check to surface genuinely-unclassified routes during development — that's the point.
3. Add `catalog-auth-convention.test.ts` (next to the walker): for every catalog entity (`CATALOG_ENTITY_KEYS`), assert the standard `edit` / `new` / `delete` route files exist and import the expected gating helpers.
4. Refactor `entity-meta.test.ts` to consume `allRoutes()` + `classifyRoute()`; drop `ROUTE_DIR_TO_KEY` / `UNMAPPED_ROUTE_DIRS`.
5. Open PR. The follow-on work in [`Robots.md`](Robots.md), [`Sitemap.md`](Sitemap.md), [`NoindexMeta.md`](NoindexMeta.md) and [`CanonicalUrl.md`](CanonicalUrl.md) can stack on top.

## Deliberately not in this plan

- **Per-route `searchEngineInclusion` exports.** An earlier draft co-located a yes/no export on every `+page.ts`. Dropped because it conflicts with model-driven metadata: ~140 of those declarations would be mechanical reproductions of class-level facts and a new catalog entity would silently slip through unless someone remembered to add five more.
- **Auth-mechanism enforcement.** An earlier draft folded in a test that flagged ad-hoc `if (!locals.user) throw redirect(...)` blocks. Real concern, separate scope — should ship as its own grep-based test if it ships at all, not bundled here.
- **A general per-route metadata layer.** The module is named `route-metadata.server.ts` only because the test file naturally pairs with it; resist adding speculative per-route fields. Add them when there's a real second consumer.
