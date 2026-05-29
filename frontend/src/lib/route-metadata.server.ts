/**
 * Single source of truth for "is this route indexable by search engines?".
 */

import type { RouteId } from '$app/types';
import { CATALOG_ENTITY_KEYS, ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';

/**
 * Non-catalog routes that should be indexed by search engines.
 *
 * Values are SvelteKit `page.route.id` form (`[slug]` params and `(group)`
 * directories preserved), NOT resolved URLs — `/(legal)/privacy`, not `/privacy`.
 */
export const SEARCH_ENGINE_INDEXABLE_ROUTE_IDS = [
  '/',
  '/about',
  '/about/people',
  '/(legal)/privacy',
  '/(legal)/terms',
  '/(legal)/licensing',
  // Per-route product decision: a nested catalog listing under the
  // manufacturer detail. The only route of this shape today; see
  // RouteWalking.md § "Nested listings under a catalog detail".
  '/manufacturers/[slug]/systems',
] as const satisfies readonly RouteId[];

/**
 * Non-catalog routes that should NOT be indexed by search engines.
 *
 * Values are SvelteKit `page.route.id` form (`[slug]` params preserved),
 * NOT resolved URLs — `/users/[username]`, not `/users/moses`.
 */
export const SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS = [
  '/login',
  '/signup',
  '/verify-email',
  '/auth/error',
  '/search',
  '/style-lab',
  '/api-docs',
  // Low search value while user pages are an activity stream rather than a
  // stable profile. Revisit if user pages grow real profile content.
  '/users/[username]',
  '/changesets',
  '/review',
  '/kiosk',
  '/_sentry_test',
] as const satisfies readonly RouteId[];

/**
 * Indexable dynamic routes whose `[slug]` param is fed by a catalog entity's
 * slugs but whose route ID is NOT a `catalog-*` shape (so it can't be reached
 * via `catalogRoutesByEntity()`). Maps the route ID to the entity whose
 * `sitemap_queryset()` supplies its slugs and `lastmod`.
 *
 * Today: just `/manufacturers/[slug]/systems` under `manufacturer`. A new
 * entry must be on a route that is also in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`
 * and must NOT name a `catalog-*` route ID (those are already wired through
 * `catalogRoutesByEntity()` and would double-emit). Parity tests in
 * `route-metadata.test.ts` pin both invariants at runtime; the
 * `satisfies` clause pins the key/value types at typecheck.
 *
 * `lastmod` for these routes is the parent entity's `_sitemap_lastmod` — an
 * acknowledged under-report when the listing's content changes without
 * bumping the parent (e.g. a new System linked to a Manufacturer). Revisit
 * per-route lastmod widening if/when traffic data shows lost re-crawls.
 */
export const LISTED_INDEXABLE_ENTITY_SLUG_SOURCE = {
  '/manufacturers/[slug]/systems': 'manufacturer',
} as const satisfies Partial<Record<RouteId, CatalogEntityKey>>;

/** Classification of a SvelteKit route for search engine indexing purposes. */
export type RouteClass =
  | { kind: 'catalog-listing'; entity: CatalogEntityKey }
  | { kind: 'catalog-detail'; entity: CatalogEntityKey }
  | { kind: 'catalog-edit-history'; entity: CatalogEntityKey }
  | { kind: 'catalog-sources'; entity: CatalogEntityKey }
  | { kind: 'catalog-edit'; entity: CatalogEntityKey }
  | { kind: 'catalog-new'; entity: CatalogEntityKey }
  | { kind: 'catalog-delete'; entity: CatalogEntityKey }
  | { kind: 'auth-gated' } // non-catalog, via import scan
  | { kind: 'listed-indexable' }
  | { kind: 'listed-non-indexable' }
  | { kind: 'unclassified' };

/** `RouteClass` variants that carry an `entity` reference. */
export type CatalogRouteClass = Extract<RouteClass, { entity: CatalogEntityKey }>;

/** Type guard for `CatalogRouteClass`. */
export function isCatalogRoute(cls: RouteClass): cls is CatalogRouteClass {
  return 'entity' in cls;
}

// Index: entity_type_plural → catalog ENTITY_META key. Built once at module
// load. Catalog-only: this classifies catalog detail/edit routes, so it must
// not pick up a future non-catalog entity (e.g. user) — iterate the catalog
// subset, not all of ENTITY_META.
const PLURAL_TO_KEY: ReadonlyMap<string, CatalogEntityKey> = new Map(
  CATALOG_ENTITY_KEYS.map((key) => [ENTITY_META[key].entity_type_plural, key]),
);

// Matches both /{plural}/[slug]/... and /{plural}/[...path]/... in route-pattern form.
// CONVENTION: every catalog entity's detail param is named `[slug]` (or
// `[...path]` for Location's multi-segment public_id). A new entity using a
// different param name (e.g. `[id]`, `[handle]`) will fall through to
// `unclassified` — the fix is to rename the param to `[slug]` or extend
// this regex. The convention keeps the matcher trivial.
const PUBLIC_ID_SEGMENT_RE = /^\[(?:slug|\.\.\.path)\]$/;

const INDEXABLE_SET: ReadonlySet<string> = new Set(SEARCH_ENGINE_INDEXABLE_ROUTE_IDS);
const NON_INDEXABLE_SET: ReadonlySet<string> = new Set(SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS);

// Precomputed at module load: route-ID prefixes whose +layout.server.ts
// (or any ancestor's) imports $lib/require-capability.server. Vite resolves
// the glob at build time and inlines each layout's source as a string, so
// no filesystem I/O happens at runtime.
const AUTH_GATED_PREFIXES: ReadonlySet<string> = buildAuthGatedPrefixes();

function buildAuthGatedPrefixes(): ReadonlySet<string> {
  const modules = import.meta.glob('/src/routes/**/+layout.server.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>;
  const prefixes = new Set<string>();
  for (const [path, source] of Object.entries(modules)) {
    if (!/from\s+['"]\$lib\/require-capability\.server['"]/.test(source)) continue;
    // /src/routes/admin/+layout.server.ts → /admin
    const prefix = path.replace(/^\/src\/routes/, '').replace(/\/\+layout\.server\.ts$/, '');
    if (prefix === '') {
      // Root +layout.server.ts gating everything would silently make every
      // non-catalog route auth-gated (and therefore non-indexable) with no
      // direct test failure pointing at this file. Refuse to load.
      throw new Error(
        'route-metadata: root +layout.server.ts must not import $lib/require-capability.server. ' +
          'Move the gate to a more specific layout (e.g. /admin/+layout.server.ts).',
      );
    }
    prefixes.add(prefix);
  }
  return prefixes;
}

function classifyCatalog(id: string): RouteClass | null {
  // /(legal)/privacy → segments = ['(legal)', 'privacy'] — won't match any plural, returns null.
  const segments = id === '/' ? [] : id.slice(1).split('/');
  if (segments.length === 0) return null;

  const key = PLURAL_TO_KEY.get(segments[0]);
  if (!key) return null;

  // /{plural}
  if (segments.length === 1) return { kind: 'catalog-listing', entity: key };

  // /{plural}/new
  if (segments.length === 2 && segments[1] === 'new') {
    return { kind: 'catalog-new', entity: key };
  }

  // From here on, the second segment must be a public-id slot.
  if (!PUBLIC_ID_SEGMENT_RE.test(segments[1])) return null;

  const tail = segments.slice(2);

  // /{plural}/[public-id]
  if (tail.length === 0) return { kind: 'catalog-detail', entity: key };

  if (tail.length === 1) {
    switch (tail[0]) {
      case 'edit-history':
        return { kind: 'catalog-edit-history', entity: key };
      case 'sources':
        return { kind: 'catalog-sources', entity: key };
      case 'edit':
        return { kind: 'catalog-edit', entity: key };
      case 'delete':
        return { kind: 'catalog-delete', entity: key };
      case 'new':
        return { kind: 'catalog-new', entity: key };
    }
    return null;
  }

  // /{plural}/[public-id]/edit/[section]. The param name `[section]` is
  // a hardcoded convention — a different name would fall through.
  if (tail.length === 2 && tail[0] === 'edit' && tail[1] === '[section]') {
    return { kind: 'catalog-edit', entity: key };
  }

  // Nested-create: /{outer-plural}/[public-id]/{inner-plural}/new
  if (tail.length === 2 && tail[1] === 'new') {
    const inner = PLURAL_TO_KEY.get(tail[0]);
    if (inner) return { kind: 'catalog-new', entity: inner };
  }

  return null;
}

// Pure prefix-match against the auth-gate set. Used by classifyRoute AFTER
// classifyCatalog has had its chance — catalog-edit routes also match the
// prefix set (their layouts gate too) but get claimed as catalog-edit first.
function matchesAuthGatePrefix(id: string): boolean {
  for (const prefix of AUTH_GATED_PREFIXES) {
    if (id === prefix || id.startsWith(prefix + '/')) return true;
  }
  return false;
}

/** Classify a SvelteKit route ID into an search engine indexing bucket. */
export function classifyRoute(id: RouteId): RouteClass {
  const catalog = classifyCatalog(id);
  if (catalog) return catalog;
  if (matchesAuthGatePrefix(id)) return { kind: 'auth-gated' };
  if (INDEXABLE_SET.has(id)) return { kind: 'listed-indexable' };
  if (NON_INDEXABLE_SET.has(id)) return { kind: 'listed-non-indexable' };
  return { kind: 'unclassified' };
}

/**
 * Whether a route should be exposed to search engines.
 *
 * @throws if the route is unclassified.
 */
export function isSearchEngineIndexable(id: RouteId): boolean {
  const c = classifyRoute(id);
  switch (c.kind) {
    case 'catalog-detail':
    case 'catalog-edit-history':
    case 'catalog-sources':
    case 'listed-indexable':
      return true;
    case 'catalog-listing':
    case 'catalog-edit':
    case 'catalog-new':
    case 'catalog-delete':
    case 'auth-gated':
    case 'listed-non-indexable':
      return false;
    case 'unclassified':
      throw new Error(
        `Route ${id} is unclassified. Add it to a catalog convention, an auth-gated layout, or one of the SEARCH_ENGINE_*_ROUTE_IDS allowlists in route-metadata.server.ts.`,
      );
  }
}

/**
 * Enumerate every route ID that has a `+page.svelte`.
 *
 * Excludes `+server.ts`-only endpoints (like `/__health`) and directory-only
 * routes that exist solely as containers for nested routes (like
 * `/titles/[slug]/models`, which has no `+page.svelte` of its own).
 */
export function allRoutes(): RouteId[] {
  // Match both +page.svelte and +page@*.svelte (the reset-layout form, used
  // by every catalog /delete page and the nested-create pages). Both
  // resolve to the same route ID — the @-suffix only changes which layout
  // chain renders the page, not the URL. A naïve glob of +page.svelte
  // would silently exclude 22 of 157 page routes from classification.
  const pages = import.meta.glob('/src/routes/**/+page*.svelte', { eager: false });
  return Object.keys(pages)
    .map((p) => {
      const trimmed = p.replace(/^\/src\/routes/, '').replace(/\/\+page[^/]*\.svelte$/, '');
      return trimmed === '' ? '/' : trimmed;
    })
    .sort() as RouteId[];
}

/**
 * Group page routes by entity. Walks `allRoutes()`, classifies each one,
 * keeps the catalog-* routes that satisfy `predicate`, and buckets them by
 * the owning entity. `predicate` receives both the classification and the
 * route ID so callers can filter on either (e.g. catalog-edit routes that
 * end in `/edit` to skip `/edit/[section]`).
 */
export function catalogRoutesByEntity(
  predicate: (cls: CatalogRouteClass, id: RouteId) => boolean,
): Map<CatalogEntityKey, RouteId[]> {
  const out = new Map<CatalogEntityKey, RouteId[]>();
  for (const id of allRoutes()) {
    const cls = classifyRoute(id);
    if (!isCatalogRoute(cls) || !predicate(cls, id)) continue;
    const arr = out.get(cls.entity) ?? [];
    arr.push(id);
    out.set(cls.entity, arr);
  }
  return out;
}
