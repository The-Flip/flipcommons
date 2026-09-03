import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { validateXML } from 'xmllint-wasm';
import type { SitemapResponseSchema } from '$lib/api/schema';
import type { RouteId } from '$app/types';
import {
  allRoutes,
  classifyRoute,
  isCatalogRoute,
  isSearchEngineIndexable,
  LISTED_INDEXABLE_ENTITY_SLUG_SOURCE,
} from '$lib/route-metadata.server';
import {
  MAX_URLS_PER_PAGE,
  splitRouteAtParam,
  stripRouteGroups,
} from '$lib/sitemap-helpers.server';
import { CATALOG_ENTITY_KEYS, type CatalogEntityKey } from '$lib/entities/entity-meta';

const SITEMAP_XSD = readFileSync(
  fileURLToPath(new URL('../../tests/fixtures/sitemap-0.9.xsd', import.meta.url)),
  'utf8',
);

// Mocks must be hoisted ABOVE the route module import. The route file's
// module-level code runs once at import (it caches `allRoutes()` etc) — by
// then env + api-client mocks are wired so subsequent requests see them.
const { mockEnv, mockGet, mockCreateServerClient } = vi.hoisted(() => ({
  mockEnv: {} as Record<string, string>,
  mockGet: vi.fn(),
  mockCreateServerClient: vi.fn(),
}));

vi.mock('$env/dynamic/private', () => ({ env: mockEnv }));
vi.mock('$lib/api/server', () => ({
  createServerClient: mockCreateServerClient,
}));

import { GET } from './+server';

function callGet(
  opts: { page?: string; origin?: string; ifNoneMatch?: string } = {},
): Promise<Response> {
  const origin = opts.origin ?? 'http://localhost:5173';
  const headers = opts.ifNoneMatch ? { 'If-None-Match': opts.ifNoneMatch } : undefined;
  return GET({
    fetch,
    url: new URL(`${origin}/sitemap${opts.page ? opts.page : ''}.xml`),
    request: new Request(origin, { headers }),
    params: { page: opts.page },
  } as unknown as Parameters<typeof GET>[0]) as Promise<Response>;
}

function setApiResponse(body: SitemapResponseSchema) {
  mockGet.mockResolvedValue({ data: body, error: undefined });
  mockCreateServerClient.mockReturnValue({ GET: mockGet });
}

function setApiError() {
  mockGet.mockResolvedValue({ data: undefined, error: { detail: 'boom' } });
  mockCreateServerClient.mockReturnValue({ GET: mockGet });
}

describe('GET /sitemap.xml', () => {
  beforeEach(() => {
    for (const key of Object.keys(mockEnv)) delete mockEnv[key];
    mockEnv.ALLOW_SEARCH_ENGINE_INDEXING = 'true';
    mockEnv.SITE_ORIGIN = 'https://flipcommons.org';
    mockGet.mockReset();
    mockCreateServerClient.mockReset();
    setApiResponse({ feeds: [] });
  });

  it('returns 404 when ALLOW_SEARCH_ENGINE_INDEXING is not "true"', async () => {
    delete mockEnv.ALLOW_SEARCH_ENGINE_INDEXING;
    const response = await callGet();
    expect(response.status).toBe(404);
    // Never edge-cached: flipping the deploy to indexable must take effect at
    // once, and a bare response would inherit Bunny's 30-day default.
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('returns 502 when the Django client returns an error', async () => {
    setApiError();
    const response = await callGet();
    expect(response.status).toBe(502);
    // A cached 502 would outlive the Django outage that caused it.
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('serves a public, cacheable Cache-Control', async () => {
    const response = await callGet();
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('public, max-age=3600');
  });

  describe('conditional requests', () => {
    const feedWith = (slug: string): SitemapResponseSchema => ({
      feeds: [
        {
          kind: 'title',
          entries: [{ slug, lastmod: '2026-01-01' }],
          detail_excluded_slugs: [],
          max_lastmod: '2026-01-01',
        },
      ],
    });

    it('serves a weak ETag alongside the body', async () => {
      const response = await callGet();
      expect(response.status).toBe(200);
      expect(response.headers.get('etag')).toMatch(/^W\/"[\w-]+"$/);
    });

    it('304s a request whose If-None-Match already holds the document', async () => {
      const etag = (await callGet()).headers.get('etag');
      const response = await callGet({ ifNoneMatch: etag! });
      expect(response.status).toBe(304);
      expect(await response.text()).toBe('');
    });

    it('repeats Cache-Control and ETag on the 304, and omits Content-Type', async () => {
      const etag = (await callGet()).headers.get('etag');
      const response = await callGet({ ifNoneMatch: etag! });
      expect(response.headers.get('cache-control')).toBe('public, max-age=3600');
      expect(response.headers.get('etag')).toBe(etag);
      expect(response.headers.get('content-type')).toBeNull();
    });

    it('serves the body when the held tag is stale', async () => {
      setApiResponse(feedWith('old-title'));
      const stale = (await callGet()).headers.get('etag');
      setApiResponse(feedWith('new-title'));
      const response = await callGet({ ifNoneMatch: stale! });
      expect(response.status).toBe(200);
      expect(await response.text()).toContain('new-title');
    });

    it('tags each page of a sitemapindex separately', async () => {
      setApiResponse({
        feeds: [
          {
            kind: 'title',
            entries: Array.from({ length: MAX_URLS_PER_PAGE + 10 }, (_, i) => ({
              slug: `t${i}`,
              lastmod: '2026-01-01',
            })),
            detail_excluded_slugs: [],
            max_lastmod: '2026-01-01',
          },
        ],
      });
      const first = (await callGet({ page: '1' })).headers.get('etag');
      const second = (await callGet({ page: '2' })).headers.get('etag');
      expect(first).not.toBe(second);
      // A page-1 tag must not silently 304 a request for page 2.
      expect((await callGet({ page: '2', ifNoneMatch: first! })).status).toBe(200);
    });
  });

  it('renders Title detail URLs from a title feed, not the provenance subroutes', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'title',
          entries: [
            { slug: 't1', lastmod: '2026-01-01T00:00:00Z' },
            { slug: 't2', lastmod: '2026-02-01T00:00:00Z' },
          ],
          detail_excluded_slugs: [],
          max_lastmod: '2026-02-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    const xml = await response.text();
    expect(xml).toContain('https://flipcommons.org/titles/t1');
    expect(xml).not.toContain('https://flipcommons.org/titles/t1/edit-history');
    expect(xml).not.toContain('https://flipcommons.org/titles/t1/sources');
    expect(xml).toContain('https://flipcommons.org/titles/t2');
    expect(xml).toContain('<lastmod>2026-01-01T00:00:00Z</lastmod>');
    expect(xml).toContain('<lastmod>2026-02-01T00:00:00Z</lastmod>');
  });

  it('includes the catalog listing page with the feed max_lastmod', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'title',
          entries: [
            { slug: 't1', lastmod: '2026-01-01T00:00:00Z' },
            { slug: 't2', lastmod: '2026-02-01T00:00:00Z' },
          ],
          detail_excluded_slugs: [],
          max_lastmod: '2026-02-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    const xml = await response.text();
    // The Title feed's max_lastmod keys to the games listing (the override),
    // not /titles — which is a redirect endpoint, absent from the sitemap.
    expect(xml).toMatch(
      /<loc>https:\/\/flipcommons\.org\/games<\/loc>\s*<lastmod>2026-02-01T00:00:00Z<\/lastmod>/,
    );
    expect(xml).not.toMatch(/<loc>https:\/\/flipcommons\.org\/titles<\/loc>/);
  });

  // Single-Model Title members are excluded from `/models/[slug]`; their
  // /edit-history and /sources are absent like every other entity's, since
  // those subroutes are not indexable.
  it('applies detail_excluded_slugs to catalog-detail', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'model',
          entries: [
            { slug: 'sm1', lastmod: '2026-01-01T00:00:00Z' },
            { slug: 'mm2', lastmod: '2026-02-01T00:00:00Z' },
          ],
          detail_excluded_slugs: ['sm1'],
          max_lastmod: '2026-02-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    const xml = await response.text();
    expect(xml).not.toMatch(/<loc>https:\/\/flipcommons\.org\/models\/sm1<\/loc>/);
    expect(xml).toContain('<loc>https://flipcommons.org/models/mm2</loc>');
    expect(xml).not.toContain('<loc>https://flipcommons.org/models/sm1/edit-history</loc>');
    expect(xml).not.toContain('<loc>https://flipcommons.org/models/sm1/sources</loc>');
    expect(xml).not.toContain('<loc>https://flipcommons.org/models/mm2/edit-history</loc>');
  });

  it('bridges manufacturer slugs into /manufacturers/[slug]/systems via LISTED_INDEXABLE_ENTITY_SLUG_SOURCE', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'manufacturer',
          entries: [{ slug: 'stern', lastmod: '2026-03-01T00:00:00Z' }],
          detail_excluded_slugs: [],
          max_lastmod: '2026-03-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    const xml = await response.text();
    expect(xml).toContain('<loc>https://flipcommons.org/manufacturers/stern</loc>');
    expect(xml).toContain('<loc>https://flipcommons.org/manufacturers/stern/systems</loc>');
  });

  // Pins the rest-param ([...path]) substitution: a multi-segment slug
  // must render with literal slashes, not %2F. If the emitter ever
  // starts URL-encoding slug values, this test catches it.
  it('substitutes a path-shaped Location slug into the rest route literally', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'location',
          entries: [{ slug: 'a/b/c', lastmod: '2026-04-01T00:00:00Z' }],
          detail_excluded_slugs: [],
          max_lastmod: '2026-04-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    const xml = await response.text();
    expect(xml).toContain('<loc>https://flipcommons.org/locations/a/b/c</loc>');
    expect(xml).not.toContain('a%2Fb%2Fc');
  });

  it('attaches <lastmod> from STATIC_LASTMOD to auto-discovered static URLs', async () => {
    const response = await callGet();
    const xml = await response.text();
    // The static lastmods are hand-maintained; assert the URLs are present
    // and each one carries a lastmod element nearby.
    const staticUrls = ['/', '/about', '/about/people', '/privacy', '/terms', '/licensing'];
    for (const path of staticUrls) {
      const re = new RegExp(
        `<loc>https://flipcommons\\.org${path}</loc>\\s*<lastmod>\\d{4}-\\d{2}-\\d{2}</lastmod>`,
      );
      expect(xml, `expected <loc>${path}</loc> followed by <lastmod>`).toMatch(re);
    }
  });

  it('does not include any non-indexable route in the response', async () => {
    setApiResponse({ feeds: [] });
    const response = await callGet();
    const xml = await response.text();
    expect(xml).not.toContain('/login');
    expect(xml).not.toContain('/style-lab');
    expect(xml).not.toContain('/api-docs');
    expect(xml).not.toContain('/search');
    expect(xml).not.toContain('/auth/error');
  });

  it('falls back to url.origin when SITE_ORIGIN is unset', async () => {
    delete mockEnv.SITE_ORIGIN;
    const response = await callGet({ origin: 'http://localhost:5173' });
    const xml = await response.text();
    expect(xml).toContain('<loc>http://localhost:5173/</loc>');
  });

  // page=undefined is the canonical `/sitemap.xml`; page="1" is the first
  // sitemap-index subpage. Below 50k urls there's only one page so a
  // request for a later page should 404.
  it('renders a urlset for page=undefined', async () => {
    const response = await callGet();
    const xml = await response.text();
    expect(xml).toContain('<urlset');
  });

  it('caches an out-of-range page 404 like the document that defines the page set', async () => {
    const response = await callGet({ page: '99' });
    expect(response.headers.get('cache-control')).toBe('public, max-age=3600');
  });

  it('404s for an out-of-range page index', async () => {
    const response = await callGet({ page: '99' });
    expect(response.status).toBe(404);
  });

  // Production sits well under the sitemaps.org 50,000-URL page limit, so the
  // `<sitemapindex>` branch has never rendered for real. Each Title slug
  // expands to exactly one URL (its detail page), so this many slugs clears
  // the limit and exercises the split the way catalog growth will.
  describe('above the 50,000-url page limit', () => {
    const SLUGS = 51_000;
    const urlCount = (xml: string) => xml.match(/<url>/g)?.length ?? 0;

    beforeEach(() => {
      setApiResponse({
        feeds: [
          {
            kind: 'title',
            entries: Array.from({ length: SLUGS }, (_, i) => ({
              slug: `t${i}`,
              lastmod: '2026-01-01T00:00:00Z',
            })),
            detail_excluded_slugs: [],
            max_lastmod: '2026-01-01T00:00:00Z',
          },
        ],
      });
    });

    it('renders a sitemapindex pointing at every subpage', async () => {
      const xml = await (await callGet()).text();
      expect(xml).toContain('<sitemapindex');
      expect(xml).not.toContain('<urlset');
      expect(xml).toContain('<loc>https://flipcommons.org/sitemap1.xml</loc>');
      expect(xml).toContain('<loc>https://flipcommons.org/sitemap2.xml</loc>');
      expect(xml).not.toContain('<loc>https://flipcommons.org/sitemap3.xml</loc>');
    });

    it('splits every url across the subpages, dropping none', async () => {
      const first = await (await callGet({ page: '1' })).text();
      const second = await (await callGet({ page: '2' })).text();
      expect(first).toContain('<urlset');
      expect(second).toContain('<urlset');
      expect(urlCount(first)).toBe(MAX_URLS_PER_PAGE);
      expect(urlCount(second)).toBeGreaterThan(0);
      expect(urlCount(second)).toBeLessThan(MAX_URLS_PER_PAGE);

      // Re-render with no feed to count the static routes the tree currently
      // discovers, so this stays correct as static routes are added.
      setApiResponse({ feeds: [] });
      const staticUrls = urlCount(await (await callGet()).text());
      expect(urlCount(first) + urlCount(second)).toBe(SLUGS + staticUrls);
    });
  });

  // XSD validation pins XML correctness — well-formedness, element order,
  // value shapes — against the official sitemaps.org 0.9 schema. Combined
  // with the Location rest-param regression (multi-segment slug must NOT
  // be percent-encoded), this catches encoding/structure regressions that
  // hand-written assertions miss.
  it('renders XML that validates against sitemap-0.9.xsd', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'title',
          entries: [
            { slug: 'foo', lastmod: '2026-01-01T00:00:00Z' },
            { slug: 'bar-baz', lastmod: '2026-02-01T00:00:00Z' },
          ],
          detail_excluded_slugs: [],
          max_lastmod: '2026-02-01T00:00:00Z',
        },
        {
          kind: 'location',
          entries: [{ slug: 'a/b/c', lastmod: '2026-04-01T00:00:00Z' }],
          detail_excluded_slugs: [],
          max_lastmod: '2026-04-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    const xml = await response.text();

    const result = await validateXML({
      xml: [{ fileName: 'sitemap.xml', contents: xml }],
      schema: [{ fileName: 'sitemap-0.9.xsd', contents: SITEMAP_XSD }],
    });
    expect(
      result.errors,
      `Sitemap failed XSD validation:\n${result.rawOutput}\n\nXML:\n${xml}`,
    ).toEqual([]);
    expect(result.valid).toBe(true);

    // Pin the rest-param literal-slash invariant here too: an encoding
    // regression would still pass XSD (the URL would just be different)
    // but break the actual sitemap consumer contract.
    expect(xml).toContain('<loc>https://flipcommons.org/locations/a/b/c</loc>');
    expect(xml).not.toContain('a%2Fb%2Fc');
  });

  it('drops feeds whose entity has no matching route (silent opt-out)', async () => {
    setApiResponse({
      feeds: [
        {
          kind: 'nonexistent-entity-kind',
          entries: [{ slug: 'whatever', lastmod: '2026-01-01T00:00:00Z' }],
          detail_excluded_slugs: [],
          max_lastmod: '2026-01-01T00:00:00Z',
        },
      ],
    });
    const response = await callGet();
    expect(response.status).toBe(200);
    const xml = await response.text();
    expect(xml).not.toContain('/whatever');
  });

  // The additive emitter's failure mode is silence: a dynamic route nobody
  // wires to a feed just emits nothing. These tests turn that silence into
  // a CI failure — with every catalog entity's feed present, every
  // indexable dynamic route in the tree must produce at least one URL.
  describe('with one feed per catalog entity', () => {
    const slugFor = (kind: string) => `slug-for-${kind}`;

    beforeEach(() => {
      setApiResponse({
        feeds: CATALOG_ENTITY_KEYS.map((kind) => ({
          kind,
          entries: [{ slug: slugFor(kind), lastmod: '2026-01-01T00:00:00Z' }],
          detail_excluded_slugs: [],
          max_lastmod: '2026-01-01T00:00:00Z',
        })),
      });
    });

    it('emits at least one URL for every indexable dynamic route', async () => {
      const xml = await (await callGet()).text();

      const dynamicIndexable = allRoutes().filter((id) => {
        if (!id.includes('[')) return false;
        try {
          return isSearchEngineIndexable(id);
        } catch {
          return false;
        }
      });
      expect(dynamicIndexable.length).toBeGreaterThan(0);

      const listed: Partial<Record<RouteId, CatalogEntityKey>> =
        LISTED_INDEXABLE_ENTITY_SLUG_SOURCE;
      for (const id of dynamicIndexable) {
        const cls = classifyRoute(id);
        const entity = isCatalogRoute(cls) ? cls.entity : listed[id];
        expect(entity, `route ${id} has no slug-source entity`).toBeDefined();
        const slot = splitRouteAtParam(stripRouteGroups(id));
        expect(slot, `route ${id} has no fillable [slug]/[...path] segment`).not.toBeNull();
        const loc = `https://flipcommons.org${slot!.prefix}${slugFor(entity!)}${slot!.suffix}`;
        expect(xml, `route ${id} emitted no URL`).toContain(`<loc>${loc}</loc>`);
      }
    });

    it('emits every path at most once', async () => {
      const xml = await (await callGet()).text();
      const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
      expect(locs.length).toBeGreaterThan(0);
      expect(new Set(locs).size).toBe(locs.length);
    });
  });
});
