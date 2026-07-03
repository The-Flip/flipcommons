import { describe, expect, it } from 'vitest';
import { routeIdToRegex, stripRouteGroups } from './sitemap-helpers';
import { allRoutes, isSearchEngineIndexable } from './route-metadata.server';
import type { RouteId } from '$app/types';

describe('stripRouteGroups', () => {
  it.each([
    ['/', '/'],
    ['/about', '/about'],
    ['/about/people', '/about/people'],
    ['/(legal)/privacy', '/privacy'],
    ['/(legal)/terms', '/terms'],
    ['/(legal)/licensing', '/licensing'],
    // Defends against a future nested-group shape — super-sitemap strips
    // every `/(group)` segment, so we should too.
    ['/(outer)/(inner)/foo', '/foo'],
    // Group as the only segment: SvelteKit serves at `/`, not `''`.
    ['/(only)', '/'],
  ])('strips groups from %s → %s', (input, expected) => {
    expect(stripRouteGroups(input)).toBe(expected);
  });
});

describe('routeIdToRegex', () => {
  // super-sitemap@2 matches excludeRoutePatterns against the route key with
  // `(group)` segments stripped but dynamic params (`[slug]`, `[...path]`)
  // still present — no wildcard expansion of dynamic segments. These anchor
  // tests pin both directions.
  it.each<[RouteId, string, boolean]>([
    ['/login', '/login', true],
    ['/login', '/login/', false],
    ['/login', '/loginx', false],
    ['/titles/[slug]/edit', '/titles/[slug]/edit', true],
    ['/titles/[slug]/edit', '/titles/foo/edit', false],
    ['/locations/[...path]/edit', '/locations/[...path]/edit', true],
    ['/locations/[...path]/edit', '/locations/a/b/edit', false],
    // Groups are stripped before matching, mirroring super-sitemap v2.
    ['/(legal)/privacy', '/privacy', true],
    ['/(legal)/privacy', '/(legal)/privacy', false],
    // Optional param — literal, not expanded.
    ['/sitemap[[page=integer]].xml', '/sitemap[[page=integer]].xml', true],
  ])('regex for %s matches %s = %s', (id, candidate, expected) => {
    expect(routeIdToRegex(id).test(candidate)).toBe(expected);
  });

  // Snapshot: the exclude set should be exactly the non-indexable routes,
  // matched against the group-stripped route key that super-sitemap v2's
  // exclusion filter feeds in. A regression that over- or under-matched here
  // would silently drop correct URLs from the sitemap or leak non-indexable
  // ones in.
  it('excludes exactly the non-indexable routes', () => {
    const excludePatterns = allRoutes()
      .filter((id) => {
        try {
          return !isSearchEngineIndexable(id);
        } catch {
          return false;
        }
      })
      .map(routeIdToRegex);

    for (const id of allRoutes()) {
      let isIndexable: boolean;
      try {
        isIndexable = isSearchEngineIndexable(id);
      } catch {
        isIndexable = false;
      }
      const routeKey = stripRouteGroups(id);
      const matched = excludePatterns.some((re) => re.test(routeKey));
      expect(matched, `expected ${id} matched=${matched} for indexable=${isIndexable}`).toBe(
        !isIndexable,
      );
    }
  });
});
