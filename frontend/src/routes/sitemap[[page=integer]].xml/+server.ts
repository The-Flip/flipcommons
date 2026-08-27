/**
 * `/sitemap.xml` (and `/sitemap1.xml`, `/sitemap2.xml`, … when the urlset
 * crosses super-sitemap's 50,000-entry page limit and it emits a
 * `<sitemapindex>` instead).
 *
 * The handler:
 *   1. Refuses on non-indexable deploys (`ALLOW_SEARCH_ENGINE_INDEXING != "true"`).
 *   2. Fetches the consolidated `/api/sitemap/` feed from Django.
 *   3. Wires each feed's slugs into every indexable SvelteKit route ID that
 *      shares the entity (`catalogRoutesByEntity` + `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`).
 *   4. Excludes detail-URL slugs flagged non-canonical (single-Model Title members
 *      collapse to the Title page) — but keeps `/edit-history` and `/sources`.
 *   5. Attaches hand-maintained `<lastmod>` to auto-discovered static URLs.
 *   6. Lets super-sitemap render XML, split into a `<sitemapindex>` if needed.
 */

import { env } from '$env/dynamic/private';
import { getLogger } from '$lib/log';
import * as sitemap from 'super-sitemap/sveltekit';
import type { RequestHandler } from './$types';
import type { RouteId } from '$app/types';
import {
  allRoutes,
  catalogRoutesByEntity,
  classifyRoute,
  isSearchEngineIndexable,
  LISTED_INDEXABLE_ENTITY_SLUG_SOURCE,
} from '$lib/route-metadata.server';
import { listingPath } from '$lib/entities/listing-path';
import { isDeploymentSearchEngineIndexable } from '$lib/is-deployment-search-engine-indexable.server';
import { STATIC_LASTMOD } from '$lib/static-lastmod';
import { stripRouteGroups, routeIdToRegex } from '$lib/sitemap-helpers';
import { createServerClient } from '$lib/api/server';
import { CATALOG_ENTITY_KEYS, type CatalogEntityKey } from '$lib/entities/entity-meta';

const log = getLogger('sitemap');

/**
 * Type guard for the `feed.kind` wire boundary. Django serializes
 * `entity_type` as a plain string; the backend `test_entity_type_parity`
 * suite asserts every Python value is a known `CatalogEntityKey`, but
 * we cross a typed boundary here, so check rather than cast. An unknown
 * kind (renamed on the backend, removed on the frontend) is silently
 * dropped — same outcome as if `.get()` returned undefined.
 */
function isCatalogEntityKey(kind: string): kind is CatalogEntityKey {
  return (CATALOG_ENTITY_KEYS as readonly string[]).includes(kind);
}

/**
 * Throw-tolerant wrapper around `isSearchEngineIndexable`. The classifier
 * throws on unclassified routes — by design, so route authors classify
 * intentionally at lint/build time. At request time inside the sitemap
 * that discipline turns into a sharp edge: one stray unclassified route
 * 500s the entire response. Return `false` instead so the worst case is a
 * temporarily missing URL, not a missing sitemap.
 */
function safeIsIndexable(id: RouteId): boolean {
  try {
    return isSearchEngineIndexable(id);
  } catch (e) {
    log.warn(`route ${id} unclassified; treating as non-indexable`, { cause: e });
    return false;
  }
}

// --- Module-level memoization ------------------------------------------------
// `allRoutes()`, the listed map, and STATIC_LASTMOD are stable across
// requests. Compute the derived structures once at module load rather than
// rebuilding inside every GET.

// Route IDs that super-sitemap auto-discovers but must NOT emit. In v2 these
// are matched against the route key with `(group)` segments stripped but
// dynamic params (`[slug]` / `[...path]`) still present — `routeIdToRegex`
// builds a `RegExp` in exactly that shape. NOT URL form.
const EXCLUDE_ROUTE_PATTERNS: readonly RegExp[] = allRoutes()
  .filter((id) => !safeIsIndexable(id))
  .map(routeIdToRegex);

// catalog-* detail/edit-history/sources route IDs, grouped by entity.
// `safeIsIndexable` filters to the indexable catalog kinds; the `catalog-listing`
// exclusion drops the param-less listing routes (`/cabinets`, `/games`, …) —
// they carry no `[slug]`, so they belong in super-sitemap's static-route
// auto-discovery, not `paramValues`. (super-sitemap@2 throws on a `paramValues`
// key for a route that expects no params; v1 silently ignored it.) Listing
// `<lastmod>` is still attached separately via `listingLastmodByUrl` below.
const DIRECT_ROUTES_BY_ENTITY: ReadonlyMap<CatalogEntityKey, readonly RouteId[]> =
  catalogRoutesByEntity((cls, id) => cls.kind !== 'catalog-listing' && safeIsIndexable(id));

// LISTED_INDEXABLE_ENTITY_SLUG_SOURCE inverted: kind → route IDs.
const LISTED_ROUTES_BY_ENTITY: ReadonlyMap<CatalogEntityKey, readonly RouteId[]> = (() => {
  const out = new Map<CatalogEntityKey, RouteId[]>();
  for (const [routeId, kind] of Object.entries(LISTED_INDEXABLE_ENTITY_SLUG_SOURCE) as [
    RouteId,
    CatalogEntityKey,
  ][]) {
    const arr = out.get(kind) ?? [];
    arr.push(routeId);
    out.set(kind, arr);
  }
  return out;
})();

// STATIC_LASTMOD keys are route IDs (may contain `(group)` segments).
// super-sitemap's `processPaths` callback receives already-resolved URLs
// with groups stripped, so look up by URL form.
const STATIC_LASTMOD_BY_URL: ReadonlyMap<string, string> = new Map(
  Object.entries(STATIC_LASTMOD).map(([routeId, lastmod]) => [stripRouteGroups(routeId), lastmod]),
);

// Every indexable dynamic catalog route (detail/edit-history/sources plus the
// listed-slug-source routes), flattened. super-sitemap@2 requires each
// discovered dynamic route to carry ≥1 `paramValue` — so any route in this set
// that a given request produces no entries for must be excluded from discovery
// instead (see GET). This is the complete set of indexable dynamic routes: the
// static `EXCLUDE_ROUTE_PATTERNS` removes every non-indexable route, so any
// dynamic route super-sitemap still discovers is one of these.
const ALL_INDEXABLE_DYNAMIC_ROUTES: readonly RouteId[] = [
  ...DIRECT_ROUTES_BY_ENTITY.values(),
  ...LISTED_ROUTES_BY_ENTITY.values(),
].flat();

// ----------------------------------------------------------------------------

export const GET: RequestHandler = async ({ fetch, url, request, params }) => {
  if (!isDeploymentSearchEngineIndexable()) {
    return new Response('Not Found', { status: 404 });
  }

  const client = createServerClient(fetch, url, request);
  const { data, error } = await client.GET('/api/sitemap/');
  if (error || !data) {
    return new Response('Sitemap unavailable', { status: 502 });
  }

  // Populate `paramValues` from the feed, one entry per slug. super-sitemap@2
  // rejects both a missing key AND an empty array for any dynamic route it
  // discovers — so a route with zero entries this request (entity absent from
  // the feed, or every slug excluded) is left OUT of `paramValues` here and
  // excluded from discovery below, rather than seeded with an empty array.
  const paramValues: sitemap.ParamValues = {};

  // Catalog listing pages (`/games`, `/manufacturers`, …) are static routes,
  // so super-sitemap auto-discovers them but can't know their freshness. Key
  // each listing URL to its entity feed's `max_lastmod` (the newest member's
  // lastmod) and attach it in `processPaths` below, alongside STATIC_LASTMOD.
  const listingLastmodByUrl = new Map<string, string>();

  for (const feed of data.feeds) {
    if (!isCatalogEntityKey(feed.kind)) continue;

    if (feed.max_lastmod) {
      listingLastmodByUrl.set(listingPath(feed.kind), feed.max_lastmod);
    }

    const direct = DIRECT_ROUTES_BY_ENTITY.get(feed.kind) ?? [];
    const listed = LISTED_ROUTES_BY_ENTITY.get(feed.kind) ?? [];
    if (direct.length === 0 && listed.length === 0) continue;

    const excluded = new Set(feed.detail_excluded_slugs);
    for (const id of [...direct, ...listed]) {
      const cls = classifyRoute(id);
      const isDetail = cls.kind === 'catalog-detail';
      const entries =
        isDetail && excluded.size
          ? feed.entries.filter((e) => !excluded.has(e.slug))
          : feed.entries;
      // Leave zero-entry routes unset; they're excluded from discovery below.
      if (entries.length === 0) continue;
      paramValues[id] = entries.map((e) => ({
        values: [e.slug],
        lastmod: e.lastmod,
      }));
    }
  }

  // super-sitemap@2 throws on any discovered dynamic route without a
  // (non-empty) `paramValue`. Every indexable dynamic route we didn't populate
  // has zero URLs this request, so exclude it from discovery — matched, like
  // EXCLUDE_ROUTE_PATTERNS, against the group-stripped route key.
  const emptyRouteExclusions: RegExp[] = ALL_INDEXABLE_DYNAMIC_ROUTES.filter(
    (id) => !(id in paramValues),
  ).map(routeIdToRegex);

  // Same fallback pattern as `frontend/src/lib/api/server.ts`. Railway
  // builds enforce SITE_ORIGIN at build time via svelte.config.js; the
  // fallback only matters in `make dev` where the env var may be unset.
  const origin = env.SITE_ORIGIN?.trim() || url.origin;

  return sitemap.response({
    origin,
    page: params.page,
    excludeRoutePatterns: [...EXCLUDE_ROUTE_PATTERNS, ...emptyRouteExclusions],
    paramValues,
    // Static routes are auto-discovered by super-sitemap walking the routes
    // tree; `processPaths` attaches `<lastmod>` to each one from
    // STATIC_LASTMOD_BY_URL. Dynamic-route paths already carry their own
    // `lastmod` from `paramValues`, so they pass through unchanged.
    processPaths: (paths) =>
      paths.map((p) => {
        const lastmod = listingLastmodByUrl.get(p.path) ?? STATIC_LASTMOD_BY_URL.get(p.path);
        return lastmod ? { ...p, lastmod } : p;
      }),
    // super-sitemap defaults to `max-age=0, s-maxage=3600` — a shared cache
    // may hold the response, but every client must revalidate. Bunny fronts
    // the apex and respects the origin `Cache-Control` (docs/Hosting.md
    // § Bunny CDN), so `public, max-age=3600` keeps the same edge caching
    // and additionally lets crawlers reuse their own copy for the TTL.
    headers: { 'Cache-Control': 'public, max-age=3600' },
  });
};
