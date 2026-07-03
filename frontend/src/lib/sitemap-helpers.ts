/**
 * Helpers for the `/sitemap.xml` endpoint, split out for unit-testability.
 * No SvelteKit-runtime imports here so vitest can import without spinning
 * up `$env/dynamic/private` or `import.meta.glob`.
 */

/**
 * Strip `(group)` segments from a SvelteKit route ID to produce the URL
 * SvelteKit actually serves. `/(legal)/privacy` → `/privacy`. Used to key
 * `STATIC_LASTMOD` (which uses route-ID form, with groups) by URL form
 * (which is what super-sitemap's `processPaths` callback receives).
 *
 * Mirrors super-sitemap's own group-stripping pattern
 * (`removeSvelteKitRouteGroups` in
 * `super-sitemap/dist/adapters/sveltekit/internal/routes.js`) so the two stay
 * in lockstep — a divergence would mean a static route's lookup misses and
 * its `<lastmod>` silently disappears from the sitemap.
 */
export function stripRouteGroups(routeId: string): string {
  const stripped = routeId.replaceAll(/\/\([^)]+\)/g, '');
  return stripped === '' ? '/' : stripped;
}

/**
 * Convert a SvelteKit route ID into a `RegExp` for super-sitemap's
 * `excludeRoutePatterns`.
 *
 * Key invariant: super-sitemap@2 matches `excludeRoutePatterns` against the
 * route key AFTER `(group)` segments are stripped, but BEFORE dynamic params
 * are interpolated — see `createSvelteKitNormalizedRoutes` in
 * `super-sitemap/dist/adapters/sveltekit/internal/routes.js`, where the
 * exclusion `.filter()` runs after `removeSvelteKitRouteGroups()`. (This
 * changed from v1, which matched the raw route ID with groups still present.)
 * So we strip groups first, then escape regex metacharacters and anchor both
 * ends — `[slug]` / `[...path]` stay literal, matching super-sitemap's own
 * un-interpolated route key.
 *
 * v2 also requires `excludeRoutePatterns` entries to be actual `RegExp`
 * objects — passing regex strings now throws (`route-exclusion.js`).
 *
 * Limitation: optional params (`[[x]]`) are not expanded here. super-sitemap
 * expands a route's optional-segment variants BEFORE filtering, so a pattern
 * built from the un-expanded route ID would only match one variant. This is
 * fine today because the only `[[…]]` route is the sitemap `+server` endpoint,
 * which super-sitemap never discovers (it walks `+page*` files only). Revisit
 * if a non-indexable optional-param page route is ever added.
 */
export function routeIdToRegex(routeId: string): RegExp {
  const stripped = stripRouteGroups(routeId);
  return new RegExp('^' + stripped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$');
}
