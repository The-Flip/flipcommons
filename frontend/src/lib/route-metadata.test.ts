import { describe, it, expect } from 'vitest';
import type { RouteId } from '$app/types';
import {
  classifyRoute,
  isCatalogRoute,
  isSearchEngineIndexable,
  allRoutes,
  SEARCH_ENGINE_INDEXABLE_ROUTE_IDS,
  SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS,
  type RouteClass,
} from './route-metadata.server';
import type { CatalogEntityKey } from './api/catalog-meta';

// SvelteKit's ssr resolution rule: walk leaf-to-root through the
// +page.ts / +page.server.ts / +layout.ts / +layout.server.ts chain; the
// first `export const ssr = X` declaration wins, defaulting to true if none.
// This lives in the test file (not route-metadata.server.ts) because it's
// only called by the indexable-routes-are-SSR test below — the runtime
// hot path doesn't need it, and inlining 30+ raw config-file sources via
// import.meta.glob('?raw') is wasted memory on the server for non-test code.
const SSR_CONFIG_SOURCES = {
  ...(import.meta.glob('/src/routes/**/+page.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
  ...(import.meta.glob('/src/routes/**/+page.js', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
  ...(import.meta.glob('/src/routes/**/+page.server.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
  ...(import.meta.glob('/src/routes/**/+layout.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
  ...(import.meta.glob('/src/routes/**/+layout.js', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
  ...(import.meta.glob('/src/routes/**/+layout.server.ts', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>),
};

// Within a single route level we check files in this order:
//   +page.ts → +page.js → +page.server.ts → +layout.ts → +layout.js → +layout.server.ts
// matching SvelteKit's universal-over-server precedence for page options at
// the same level. First match wins; we don't merge or look for conflicts —
// this codebase has at most one `ssr =` declaration per route, so the
// question "what if both .ts and .server.ts disagree at the same level"
// hasn't come up.
function resolveSsr(id: RouteId): boolean {
  const segments = id === '/' ? [] : id.slice(1).split('/');
  for (let i = segments.length; i >= 0; i--) {
    const level = i === 0 ? '' : '/' + segments.slice(0, i).join('/');
    const isLeaf = i === segments.length;
    const candidates: string[] = [];
    if (isLeaf) {
      candidates.push(
        `/src/routes${level}/+page.ts`,
        `/src/routes${level}/+page.js`,
        `/src/routes${level}/+page.server.ts`,
      );
    }
    candidates.push(
      `/src/routes${level}/+layout.ts`,
      `/src/routes${level}/+layout.js`,
      `/src/routes${level}/+layout.server.ts`,
    );
    for (const path of candidates) {
      const src = SSR_CONFIG_SOURCES[path];
      if (src === undefined) continue;
      const m = src.match(/export\s+const\s+ssr\s*=\s*(true|false)\b/);
      if (m) return m[1] === 'true';
    }
  }
  return true;
}

describe('route-metadata', () => {
  it('every route is classified', () => {
    const unclassified = allRoutes().filter((id) => classifyRoute(id).kind === 'unclassified');
    expect(
      unclassified,
      `Add each route to a catalog convention, an auth-gated layout, or one of the two ` +
        `SEARCH_ENGINE_*_ROUTE_IDS allowlists in route-metadata.server.ts.`,
    ).toEqual([]);
  });

  it('every indexable route resolves to ssr === true', () => {
    const indexable = allRoutes().filter((id) => isSearchEngineIndexable(id));
    const nonSsr = indexable.filter((id) => !resolveSsr(id));
    expect(
      nonSsr,
      `Indexable routes must be SSR-rendered. Either flip ssr back to true on the ancestor ` +
        `that disabled it, or remove the route from SEARCH_ENGINE_INDEXABLE_ROUTE_IDS.`,
    ).toEqual([]);
  });

  it('the two allowlists are disjoint', () => {
    const indexable = new Set<string>(SEARCH_ENGINE_INDEXABLE_ROUTE_IDS);
    const overlap = SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS.filter((id) => indexable.has(id));
    expect(overlap, 'A route ID cannot appear in both allowlists').toEqual([]);
  });

  // Anchor sanity. Inputs are in route-pattern form (the shape page.route.id
  // has at runtime). Defends against "walker returned nothing, so all
  // assertions trivially pass." The fourth slot is the expected entity for
  // catalog rows; null for non-catalog rows. Checking entity catches
  // PLURAL_TO_KEY swaps that would leave the kind right but the entity wrong.
  type Anchor = readonly [RouteId, RouteClass['kind'], boolean, CatalogEntityKey | null];
  const ANCHORS: ReadonlyArray<Anchor> = [
    ['/', 'listed-indexable', true, null],
    ['/about', 'listed-indexable', true, null],
    ['/about/people', 'listed-indexable', true, null],
    ['/(legal)/privacy', 'listed-indexable', true, null],
    ['/manufacturers/[slug]/systems', 'listed-indexable', true, null],
    ['/titles', 'catalog-listing', false, 'title'],
    ['/titles/[slug]', 'catalog-detail', true, 'title'],
    ['/titles/[slug]/edit-history', 'catalog-edit-history', true, 'title'],
    ['/titles/[slug]/sources', 'catalog-sources', true, 'title'],
    ['/titles/[slug]/edit', 'catalog-edit', false, 'title'],
    ['/titles/[slug]/edit/[section]', 'catalog-edit', false, 'title'],
    ['/titles/[slug]/delete', 'catalog-delete', false, 'title'],
    ['/titles/new', 'catalog-new', false, 'title'],
    ['/titles/[slug]/models/new', 'catalog-new', false, 'model'],
    ['/manufacturers/[slug]/corporate-entities/new', 'catalog-new', false, 'corporate-entity'],
    ['/locations/[...path]', 'catalog-detail', true, 'location'],
    ['/locations/[...path]/edit', 'catalog-edit', false, 'location'],
    ['/login', 'listed-non-indexable', false, null],
    ['/users/[username]', 'listed-non-indexable', false, null],
    ['/admin', 'auth-gated', false, null],
    ['/admin/dashboard', 'auth-gated', false, null],
    // Pins the prefix-match off-by-one: /kiosk/edit is the layout's own
    // page (no trailing slash), not just a parent of /kiosk/edit/[id].
    ['/kiosk/edit', 'auth-gated', false, null],
    ['/kiosk/edit/[id]', 'auth-gated', false, null],
  ];

  it.each(ANCHORS)(
    'classifies %s as %s (indexable=%s, entity=%s)',
    (id, kind, indexable, entity) => {
      const cls = classifyRoute(id);
      expect(cls.kind).toBe(kind);
      expect(isSearchEngineIndexable(id)).toBe(indexable);
      if (entity === null) {
        expect(isCatalogRoute(cls)).toBe(false);
      } else {
        // Two-step check so a regression to a non-catalog kind reports
        // "expected false to be true" (clear), not "expected false to be
        // 'title'" from a short-circuited `cls && cls.entity` expression.
        expect(isCatalogRoute(cls)).toBe(true);
        if (isCatalogRoute(cls)) expect(cls.entity).toBe(entity);
      }
    },
  );
});
