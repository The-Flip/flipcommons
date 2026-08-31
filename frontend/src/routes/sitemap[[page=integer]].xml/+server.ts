/**
 * `/sitemap.xml` (and `/sitemap1.xml`, `/sitemap2.xml`, … when the urlset
 * crosses the sitemaps.org 50,000-entry page limit and the base URL becomes
 * a `<sitemapindex>`).
 *
 * The handler:
 *   1. Refuses on non-indexable deploys (`ALLOW_SEARCH_ENGINE_INDEXING != "true"`).
 *   2. Fetches the consolidated `/api/sitemap/` feed from Django.
 *   3. Emits URLs additively: one per static indexable route, plus one per
 *      (route, slug) pair for every indexable dynamic route wired to the
 *      feed's entity (`catalogRoutesByEntity` + `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`).
 *   4. Excludes detail-URL slugs flagged non-canonical (single-Model Title members
 *      collapse to the Title page) — but keeps `/edit-history` and `/sources`.
 *   5. Attaches `<lastmod>`: per-entry for dynamic URLs, the feed's
 *      `max_lastmod` for listing pages, hand-maintained `STATIC_LASTMOD` for
 *      the rest.
 *
 * Additive means a dynamic route nobody wired to a feed silently emits
 * nothing; the wiring-completeness test in `sitemap.test.ts` turns that
 * silence into a CI failure.
 */

import { env } from '$env/dynamic/private';
import { getLogger } from '$lib/log';
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
import {
  MAX_URLS_PER_PAGE,
  renderSitemapIndex,
  renderUrlset,
  splitRouteAtParam,
  stripRouteGroups,
  urlElement,
} from '$lib/sitemap-helpers';
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

/**
 * One indexable dynamic route, ready to emit `prefix + slug + suffix` per
 * feed entry. `isDetail` marks the `catalog-detail` route, the only shape
 * that honors the feed's `detail_excluded_slugs` (non-canonical detail URLs
 * are dropped; their `/edit-history` and `/sources` URLs are kept).
 */
interface SlugRouteEmitter {
  prefix: string;
  suffix: string;
  isDetail: boolean;
}

// --- Module-level memoization ------------------------------------------------
// `allRoutes()`, the listed map, and STATIC_LASTMOD are stable across
// requests. Compute the derived structures once at module load rather than
// rebuilding inside every GET.

// STATIC_LASTMOD keys are route IDs (may contain `(group)` segments); the
// emission loop works in URL form, so key by URL form.
const STATIC_LASTMOD_BY_URL: ReadonlyMap<string, string> = new Map(
  Object.entries(STATIC_LASTMOD).map(([routeId, lastmod]) => [stripRouteGroups(routeId), lastmod]),
);

// Every static (param-less) indexable route, in URL form — the home page,
// the about/legal pages, and the catalog listing pages.
const STATIC_INDEXABLE_URLS: readonly string[] = allRoutes()
  .filter((id) => !id.includes('[') && safeIsIndexable(id))
  .map(stripRouteGroups);

// Every indexable dynamic route, grouped by the entity whose feed supplies
// its slugs: the catalog detail/edit-history/sources routes (by route
// convention) plus the LISTED_INDEXABLE_ENTITY_SLUG_SOURCE routes (declared).
const EMITTERS_BY_ENTITY: ReadonlyMap<CatalogEntityKey, readonly SlugRouteEmitter[]> = (() => {
  const out = new Map<CatalogEntityKey, SlugRouteEmitter[]>();
  const add = (entity: CatalogEntityKey, id: RouteId, isDetail: boolean) => {
    const slot = splitRouteAtParam(stripRouteGroups(id));
    if (!slot) {
      // A wired route this helper can't fill from one slug (no [slug] /
      // [...path] segment, or a second dynamic segment). Skipping keeps the
      // sitemap serving; the wiring-completeness test fails in CI.
      log.warn(`route ${id} has no single [slug]/[...path] segment; omitted from sitemap`);
      return;
    }
    const arr = out.get(entity) ?? [];
    arr.push({ ...slot, isDetail });
    out.set(entity, arr);
  };
  const catalogRoutes = catalogRoutesByEntity(
    (cls, id) => cls.kind !== 'catalog-listing' && safeIsIndexable(id),
  );
  for (const [entity, ids] of catalogRoutes) {
    for (const id of ids) add(entity, id, classifyRoute(id).kind === 'catalog-detail');
  }
  for (const [id, entity] of Object.entries(LISTED_INDEXABLE_ENTITY_SLUG_SOURCE) as [
    RouteId,
    CatalogEntityKey,
  ][]) {
    add(entity, id, false);
  }
  return out;
})();

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

  // Same fallback pattern as `frontend/src/lib/api/server.ts`. Railway
  // builds enforce SITE_ORIGIN at build time via svelte.config.js; the
  // fallback only matters in `make dev` where the env var may be unset.
  const origin = env.SITE_ORIGIN?.trim() || url.origin;

  // Catalog listing pages (`/games`, `/manufacturers`, …) are static routes,
  // so their freshness isn't in any per-entry lastmod. Key each listing URL
  // to its entity feed's `max_lastmod` (the newest member's lastmod).
  const listingLastmodByUrl = new Map<string, string>();
  for (const feed of data.feeds) {
    if (isCatalogEntityKey(feed.kind) && feed.max_lastmod) {
      listingLastmodByUrl.set(listingPath(feed.kind), feed.max_lastmod);
    }
  }

  // Pre-rendered `<url>` elements, deduplicated by path (first wins). Kept
  // as one flat array so pagination is a slice.
  const seen = new Set<string>();
  const urlElements: string[] = [];
  const push = (path: string, lastmod: string | undefined) => {
    if (seen.has(path)) return;
    seen.add(path);
    urlElements.push(urlElement(origin + path, lastmod));
  };

  for (const path of STATIC_INDEXABLE_URLS) {
    push(path, listingLastmodByUrl.get(path) ?? STATIC_LASTMOD_BY_URL.get(path));
  }

  for (const feed of data.feeds) {
    if (!isCatalogEntityKey(feed.kind)) continue;
    const emitters = EMITTERS_BY_ENTITY.get(feed.kind);
    if (!emitters) continue;
    const excluded = new Set(feed.detail_excluded_slugs);
    for (const { prefix, suffix, isDetail } of emitters) {
      for (const entry of feed.entries) {
        if (isDetail && excluded.has(entry.slug)) continue;
        push(prefix + entry.slug + suffix, entry.lastmod);
      }
    }
  }

  const headers = {
    'Content-Type': 'application/xml',
    // A shared cache (Bunny fronts the apex and respects the origin
    // `Cache-Control` — docs/Hosting.md § Bunny CDN) may hold the response
    // for the TTL, and crawlers may reuse their own copy for the same
    // window.
    'Cache-Control': 'public, max-age=3600',
  };

  if (!params.page) {
    const body =
      urlElements.length <= MAX_URLS_PER_PAGE
        ? renderUrlset(urlElements)
        : renderSitemapIndex(origin, Math.ceil(urlElements.length / MAX_URLS_PER_PAGE));
    return new Response(body, { headers });
  }

  // The `integer` param matcher guarantees a positive integer (no leading
  // zeros), so the only failure mode left is a page past the end.
  const page = Number(params.page);
  const pageElements = urlElements.slice((page - 1) * MAX_URLS_PER_PAGE, page * MAX_URLS_PER_PAGE);
  if (pageElements.length === 0) {
    return new Response('Page does not exist', { status: 404 });
  }
  return new Response(renderUrlset(pageElements), { headers });
};
