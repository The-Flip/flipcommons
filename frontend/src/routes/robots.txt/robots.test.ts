import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockEnv } = vi.hoisted(() => ({ mockEnv: {} as Record<string, string> }));
vi.mock('$env/dynamic/private', () => ({ env: mockEnv }));

import { GET } from './+server';

function callGet(origin = 'http://localhost:5173'): Response {
  return GET({ url: new URL(origin) } as unknown as Parameters<typeof GET>[0]) as Response;
}

describe('GET /robots.txt', () => {
  beforeEach(() => {
    for (const key of Object.keys(mockEnv)) delete mockEnv[key];
  });

  it('returns the disallow-all body when ALLOW_SEARCH_ENGINE_INDEXING is unset', async () => {
    const response = callGet();
    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(response.headers.get('Cache-Control')).toBe('public, max-age=300');
    await expect(response.text()).resolves.toMatchInlineSnapshot(`
      "User-agent: *
      Disallow: /
      "
    `);
  });

  it('returns the indexable body with Sitemap line when ALLOW_SEARCH_ENGINE_INDEXING="true"', async () => {
    mockEnv.ALLOW_SEARCH_ENGINE_INDEXING = 'true';
    mockEnv.SITE_ORIGIN = 'https://flipcommons.org';
    const response = callGet();
    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(response.headers.get('Cache-Control')).toBe('public, max-age=300');
    await expect(response.text()).resolves.toMatchInlineSnapshot(`
      "User-agent: *
      Disallow: /api/
      Sitemap: https://flipcommons.org/sitemap.xml
      "
    `);
  });

  it('falls back to the request origin when SITE_ORIGIN is unset', async () => {
    mockEnv.ALLOW_SEARCH_ENGINE_INDEXING = 'true';
    const response = callGet('http://localhost:5173');
    await expect(response.text()).resolves.toContain('Sitemap: http://localhost:5173/sitemap.xml');
  });

  // Only the literal "true" enables indexing. Anything else fails safe to the
  // disallow-all body so a typo can't silently expose preview or staging to
  // crawlers. The deploy-time check (core.E301 / core.E302) refuses any of
  // these values on a real deploy, but this is the runtime backstop.
  it.each(['false', 'True', ' true ', 'true ', '1', 'yes', ''])(
    'returns the disallow-all body for the non-"true" value %p',
    async (value) => {
      mockEnv.ALLOW_SEARCH_ENGINE_INDEXING = value;
      const response = callGet();
      await expect(response.text()).resolves.toBe('User-agent: *\nDisallow: /\n');
    },
  );
});
