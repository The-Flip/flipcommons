/**
 * `/sitemap.xml` (and `/sitemap1.xml`, `/sitemap2.xml`, … when the urlset
 * crosses 50k entries) — see `docs/plans/seo/Sitemap.md`.
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
import * as sitemap from 'super-sitemap';
import type { RequestHandler } from './$types';
import type { RouteId } from '$app/types';
import {
  allRoutes,
  catalogRoutesByEntity,
  classifyRoute,
  isSearchEngineIndexable,
  LISTED_INDEXABLE_ENTITY_SLUG_SOURCE,
} from '$lib/route-metadata.server';
import { isDeploymentSearchEngineIndexable } from '$lib/is-deployment-search-engine-indexable.server';
import { STATIC_LASTMOD } from '$lib/static-lastmod';
import { stripRouteGroups, routeIdToRegex } from '$lib/sitemap-helpers';
import { createServerClient } from '$lib/api/server';
import { CATALOG_ENTITY_KEYS, ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';

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
    console.warn(`[sitemap] route ${id} unclassified; treating as non-indexable`, e);
    return false;
  }
}

// --- Module-level memoization ------------------------------------------------
// `allRoutes()`, the listed map, and STATIC_LASTMOD are stable across
// requests. Compute the derived structures once at module load rather than
// rebuilding inside every GET.

// Route IDs that super-sitemap auto-discovers but must NOT emit. Matched
// against route-ID form (with `[slug]` / `(group)` still present) per
// super-sitemap's `filterRoutes` semantics — NOT URL form.
const EXCLUDE_ROUTE_PATTERNS: readonly string[] = allRoutes()
  .filter((id) => !safeIsIndexable(id))
  .map(routeIdToRegex);

// catalog-* detail/edit-history/sources route IDs, grouped by entity.
// `safeIsIndexable` filters to exactly the indexable catalog kinds.
const DIRECT_ROUTES_BY_ENTITY: ReadonlyMap<CatalogEntityKey, readonly RouteId[]> =
  catalogRoutesByEntity((_cls, id) => safeIsIndexable(id));

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

  // Initialize every indexable dynamic route to an empty paramValues entry
  // FIRST, then overlay feed data. super-sitemap throws on any dynamic route
  // it discovers in the file tree that lacks a paramValues key — and a
  // catalog kind with zero active rows produces no Django feed (the backend
  // skips empty feeds), so the route would otherwise crash the response.
  // Empty arrays are accepted and produce zero URLs.
  const paramValues: sitemap.ParamValues = {};
  for (const routes of DIRECT_ROUTES_BY_ENTITY.values()) {
    for (const id of routes) paramValues[id] = [];
  }
  for (const routes of LISTED_ROUTES_BY_ENTITY.values()) {
    for (const id of routes) paramValues[id] = [];
  }

  // Catalog listing pages (`/titles`, `/manufacturers`, …) are static routes,
  // so super-sitemap auto-discovers them but can't know their freshness. Key
  // each listing URL to its entity feed's `max_lastmod` (the newest member's
  // lastmod) and attach it in `processPaths` below, alongside STATIC_LASTMOD.
  const listingLastmodByUrl = new Map<string, string>();

  for (const feed of data.feeds) {
    if (!isCatalogEntityKey(feed.kind)) continue;

    if (feed.max_lastmod) {
      listingLastmodByUrl.set(`/${ENTITY_META[feed.kind].entity_type_plural}`, feed.max_lastmod);
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
      paramValues[id] = entries.map((e) => ({
        values: [e.slug],
        lastmod: e.lastmod,
      }));
    }
  }

  // Same fallback pattern as `frontend/src/lib/api/server.ts`. Railway
  // builds enforce SITE_ORIGIN at build time via svelte.config.js; the
  // fallback only matters in `make dev` where the env var may be unset.
  const origin = env.SITE_ORIGIN?.trim() || url.origin;

  return sitemap.response({
    origin,
    page: params.page,
    excludeRoutePatterns: [...EXCLUDE_ROUTE_PATTERNS],
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
    // super-sitemap@1.0.12 defaults to `max-age=0, s-maxage=3600`. We
    // override because (a) there is no shared cache today (Caddy isn't a
    // caching reverse proxy, no CDN), so `s-maxage` is a no-op; (b) we want
    // clients/crawlers to actually cache the response for the TTL.
    headers: { 'Cache-Control': 'public, max-age=3600' },
  });
};
