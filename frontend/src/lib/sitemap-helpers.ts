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
 * Mirrors super-sitemap's own group-stripping pattern (sitemap.js:267) so
 * the two stay in lockstep — a divergence would mean a static route's
 * lookup misses and its `<lastmod>` silently disappears from the sitemap.
 */
export function stripRouteGroups(routeId: string): string {
  const stripped = routeId.replaceAll(/\/\([^)]+\)/g, '');
  return stripped === '' ? '/' : stripped;
}

/**
 * Convert a SvelteKit route ID into a regex string for super-sitemap's
 * `excludeRoutePatterns`.
 *
 * Key invariant: super-sitemap applies `excludeRoutePatterns` against
 * route-ID form (with `[slug]`, `[...path]`, and `(group)` still present)
 * — NOT against resolved URLs. See `filterRoutes` in `super-sitemap/dist/sitemap.js`:
 * the patterns run BEFORE the `(group)` strip. So the regex must match the
 * literal route-ID form, which means we just escape regex metacharacters
 * and anchor both ends — no `[slug]` → wildcard rewriting needed.
 */
export function routeIdToRegex(routeId: string): string {
  return '^' + routeId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$';
}
