import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { validateXML } from 'xmllint-wasm';
import type { SitemapResponseSchema } from '$lib/api/schema';

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

function callGet(opts: { page?: string; origin?: string } = {}): Promise<Response> {
  const origin = opts.origin ?? 'http://localhost:5173';
  return GET({
    fetch,
    url: new URL(`${origin}/sitemap${opts.page ? opts.page : ''}.xml`),
    request: new Request(origin),
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
  });

  it('returns 502 when the Django client returns an error', async () => {
    setApiError();
    const response = await callGet();
    expect(response.status).toBe(502);
  });

  it('overrides super-sitemap default Cache-Control', async () => {
    const response = await callGet();
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('public, max-age=3600');
  });

  it('renders Title detail/edit-history/sources URLs from a title feed', async () => {
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
    expect(xml).toContain('https://flipcommons.org/titles/t1/edit-history');
    expect(xml).toContain('https://flipcommons.org/titles/t1/sources');
    expect(xml).toContain('https://flipcommons.org/titles/t2');
    expect(xml).toContain('<lastmod>2026-01-01T00:00:00Z</lastmod>');
    expect(xml).toContain('<lastmod>2026-02-01T00:00:00Z</lastmod>');
  });

  // Load-bearing test for the canonical-URL invariant: single-Model Title
  // members are excluded from `/models/[slug]` but kept in /edit-history
  // and /sources.
  it('applies detail_excluded_slugs to catalog-detail only', async () => {
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
    expect(xml).toContain('<loc>https://flipcommons.org/models/sm1/edit-history</loc>');
    expect(xml).toContain('<loc>https://flipcommons.org/models/sm1/sources</loc>');
    expect(xml).toContain('<loc>https://flipcommons.org/models/mm2/edit-history</loc>');
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
  // must render with literal slashes, not %2F. If super-sitemap ever
  // starts URL-encoding param values, this test catches it.
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
  // request for page="2" should 404 from super-sitemap.
  it('renders a urlset for page=undefined', async () => {
    const response = await callGet();
    const xml = await response.text();
    expect(xml).toContain('<urlset');
  });

  it('404s for an out-of-range page index', async () => {
    const response = await callGet({ page: '99' });
    expect(response.status).toBe(404);
  });

  // XSD validation pins XML correctness — well-formedness, element order,
  // value shapes — against the official sitemaps.org 0.9 schema. Combined
  // with the Location rest-param regression (multi-segment slug must NOT
  // be percent-encoded), this catches encoding/structure regressions that
  // hand-written assertions miss.
  //
  // Slug constraint reminder: super-sitemap does NOT XML-escape <loc>
  // contents (sitemap.js builds the string with template literals). That
  // works only because catalog slugs are URL-safe alphanumerics/hyphens
  // — a future slug containing `&`/`<`/`>` would produce invalid XML.
  // Slug validation is the contract that makes the no-escaping behavior
  // safe, not anything in this endpoint.
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
});
