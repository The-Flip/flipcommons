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
  // super-sitemap applies excludeRoutePatterns to route-ID form (with
  // `[slug]`, `[...path]`, and `(group)` still present), so the regex
  // should match the route ID literally — no wildcard expansion of
  // dynamic segments. These anchor tests pin both directions.
  it.each<[RouteId, string, boolean]>([
    ['/login', '/login', true],
    ['/login', '/login/', false],
    ['/login', '/loginx', false],
    ['/titles/[slug]/edit', '/titles/[slug]/edit', true],
    ['/titles/[slug]/edit', '/titles/foo/edit', false],
    ['/locations/[...path]/edit', '/locations/[...path]/edit', true],
    ['/locations/[...path]/edit', '/locations/a/b/edit', false],
    ['/(legal)/privacy', '/(legal)/privacy', true],
    ['/(legal)/privacy', '/privacy', false],
    // Optional param — literal, not expanded.
    ['/sitemap[[page=integer]].xml', '/sitemap[[page=integer]].xml', true],
  ])('regex for %s matches %s = %s', (id, candidate, expected) => {
    const re = new RegExp(routeIdToRegex(id));
    expect(re.test(candidate)).toBe(expected);
  });

  // Snapshot: the exclude set should be exactly the non-indexable routes,
  // matched literally against the route-ID-with-groups form that
  // super-sitemap's filterRoutes() feeds in. A regression that over- or
  // under-matched here would silently drop correct URLs from the sitemap
  // or leak non-indexable ones in.
  it('excludes exactly the non-indexable routes', () => {
    const excludePatterns = allRoutes()
      .filter((id) => {
        try {
          return !isSearchEngineIndexable(id);
        } catch {
          return false;
        }
      })
      .map(routeIdToRegex)
      .map((p) => new RegExp(p));

    for (const id of allRoutes()) {
      let isIndexable: boolean;
      try {
        isIndexable = isSearchEngineIndexable(id);
      } catch {
        isIndexable = false;
      }
      const matched = excludePatterns.some((re) => re.test(id));
      expect(matched, `expected ${id} matched=${matched} for indexable=${isIndexable}`).toBe(
        !isIndexable,
      );
    }
  });
});
