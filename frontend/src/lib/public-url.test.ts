import { afterEach, describe, expect, it, vi } from 'vitest';

// `publicUrl()` reads `$env/dynamic/public` and `$app/environment` at module
// scope, so each case mocks those modules and re-imports it — same pattern as
// analytics/index.test.ts.

async function loadPublicUrl(opts: {
  siteOrigin: string | undefined;
  building?: boolean;
}): Promise<typeof import('./public-url')> {
  vi.resetModules();
  vi.doMock('$env/dynamic/public', () => ({
    env: { PUBLIC_SITE_ORIGIN: opts.siteOrigin },
  }));
  vi.doMock('$app/environment', () => ({
    building: opts.building ?? false,
    browser: false,
    dev: false,
  }));
  return await import('./public-url');
}

afterEach(() => {
  vi.doUnmock('$env/dynamic/public');
  vi.doUnmock('$app/environment');
  vi.resetModules();
});

describe('publicUrl', () => {
  it('rebases a foreign-host URL onto the configured origin, keeping path and query', async () => {
    const { publicUrl } = await loadPublicUrl({ siteOrigin: 'https://flipcommons.org' });
    const url = new URL('https://flipcommons-production.up.railway.app/models/circus-11?page=2');
    expect(publicUrl(url).href).toBe('https://flipcommons.org/models/circus-11?page=2');
  });

  it('keeps a //host pathname on the configured origin (network-path reference)', async () => {
    const { publicUrl } = await loadPublicUrl({ siteOrigin: 'https://flipcommons.org' });
    const url = new URL('https://flipcommons.org//attacker.example/x');
    expect(publicUrl(url).href).toBe('https://flipcommons.org//attacker.example/x');
  });

  it('falls back to the request origin when PUBLIC_SITE_ORIGIN is unset', async () => {
    const { publicUrl } = await loadPublicUrl({ siteOrigin: undefined });
    const url = new URL('http://localhost:5173/models/circus-11');
    expect(publicUrl(url).href).toBe('http://localhost:5173/models/circus-11');
  });

  it('pageIdentity() returns origin + pathname only, pinned to the public origin', async () => {
    const { pageIdentity } = await loadPublicUrl({ siteOrigin: 'https://flipcommons.org' });
    const url = new URL('https://flipcommons-production.up.railway.app/models/circus-11?page=2#x');
    expect(pageIdentity(url)).toBe('https://flipcommons.org/models/circus-11');
  });

  it('returns the URL unchanged while prerendering (prerender.origin already pins page.url)', async () => {
    const { publicUrl } = await loadPublicUrl({
      siteOrigin: 'https://elsewhere.example',
      building: true,
    });
    const url = new URL('https://flipcommons.org/privacy');
    expect(publicUrl(url).href).toBe('https://flipcommons.org/privacy');
  });
});
