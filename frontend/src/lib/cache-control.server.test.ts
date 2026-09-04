import { describe, expect, it, vi } from 'vitest';
import type { RequestEvent } from '@sveltejs/kit';
import { cacheControlHandle } from './cache-control.server';

const ANON = 'public, s-maxage=60, max-age=0';
const AUTHED = 'private, no-cache';
const KIOSK = 'private, no-store';
const NO_STORE = 'private, no-store';

interface RunOptions {
  cookies?: Record<string, string>;
  method?: string;
  pathname?: string;
  contentType?: string;
  status?: number;
  /** A `Cache-Control` already set by the resolved response (e.g. robots.txt). */
  presetCacheControl?: string;
  /** A `Set-Cookie` the resolved response carries (e.g. a load's cookies.set). */
  setCookie?: string;
}

function runCacheControl({
  cookies = {},
  method = 'GET',
  pathname = '/',
  contentType = 'text/html',
  status = 200,
  presetCacheControl,
  setCookie,
}: RunOptions) {
  const headers: Record<string, string> = { 'content-type': contentType };
  if (presetCacheControl) headers['cache-control'] = presetCacheControl;
  if (setCookie) headers['set-cookie'] = setCookie;

  const cookieHeader = Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join('; ');

  const resolve = vi.fn(async () => new Response('<html></html>', { status, headers }));
  const event = {
    request: { method, headers: new Headers(cookieHeader ? { cookie: cookieHeader } : {}) },
    url: { pathname },
  } as unknown as RequestEvent;

  return cacheControlHandle({ event, resolve, fetch: globalThis.fetch } as never);
}

describe('cacheControlHandle', () => {
  it('stamps anonymous HTML as public + stale-while-revalidate', async () => {
    const res = await runCacheControl({});
    expect(res.headers.get('Cache-Control')).toBe(ANON);
  });

  it('stamps a sessionid request as private, no-cache', async () => {
    const res = await runCacheControl({ cookies: { sessionid: 'abc' } });
    expect(res.headers.get('Cache-Control')).toBe(AUTHED);
  });

  it('stamps a kiosk request as private, no-store', async () => {
    const res = await runCacheControl({ cookies: { mode: 'kiosk' } });
    expect(res.headers.get('Cache-Control')).toBe(KIOSK);
  });

  it('kiosk wins when both mode=kiosk and sessionid are present', async () => {
    const res = await runCacheControl({ cookies: { mode: 'kiosk', sessionid: 'abc' } });
    expect(res.headers.get('Cache-Control')).toBe(KIOSK);
  });

  it('treats mode set to a non-kiosk value as not-kiosk', async () => {
    const res = await runCacheControl({ cookies: { mode: 'something-else' } });
    expect(res.headers.get('Cache-Control')).toBe(ANON);
  });

  it('stamps anonymous __data.json (JSON content-type) — proves pathname detection', async () => {
    const res = await runCacheControl({
      pathname: '/titles/__data.json',
      contentType: 'application/json',
    });
    expect(res.headers.get('Cache-Control')).toBe(ANON);
  });

  it('stamps a sessionid __data.json request as private, no-cache', async () => {
    const res = await runCacheControl({
      pathname: '/titles/__data.json',
      contentType: 'application/json',
      cookies: { sessionid: 'abc' },
    });
    expect(res.headers.get('Cache-Control')).toBe(AUTHED);
  });

  it('preserves a Cache-Control the response already set (no clobber)', async () => {
    const res = await runCacheControl({ presetCacheControl: 'public, max-age=300' });
    expect(res.headers.get('Cache-Control')).toBe('public, max-age=300');
  });

  // Everything that is not a successful page or data request is stamped
  // `private, no-store` rather than left bare: an unstamped response reaching
  // the edge inherits the zone's 30-day default.

  it('stamps non-GET requests (form-action POSTs) private, no-store', async () => {
    const res = await runCacheControl({ method: 'POST' });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('stamps non-page JSON endpoints like /__health private, no-store', async () => {
    const res = await runCacheControl({ pathname: '/__health', contentType: 'application/json' });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('stamps error responses private, no-store (a transient 500 must not be cached)', async () => {
    const res = await runCacheControl({ status: 500 });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('stamps a 404 private, no-store (e.g. a just-created record)', async () => {
    const res = await runCacheControl({ status: 404 });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('stamps a HEAD 404 identically to a GET 404', async () => {
    const res = await runCacheControl({ method: 'HEAD', status: 404 });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('stamps a 3xx HTML redirect private, no-store', async () => {
    const res = await runCacheControl({ status: 302 });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('stamps a 3xx __data.json redirect (auth-gate bounce) private, no-store', async () => {
    // requireCapability() throws redirect on an anonymous SPA nav to an
    // auth-gated route; stamping it `public` would replay the bounce from
    // browser cache after sign-in. The pathname branch must not catch it.
    const res = await runCacheControl({
      status: 302,
      pathname: '/admin/__data.json',
      contentType: 'application/json',
    });
    expect(res.headers.get('Cache-Control')).toBe(NO_STORE);
  });

  it('never upgrades an error to the anonymous public directive', async () => {
    // The cookie branches apply only to successful pages: an anonymous 500
    // must not be shared-cached even though the request carries no cookie.
    const res = await runCacheControl({ status: 500, cookies: {} });
    expect(res.headers.get('Cache-Control')).not.toBe(ANON);
  });

  it('preserves a Cache-Control an error response already set', async () => {
    const res = await runCacheControl({ status: 404, presetCacheControl: 'public, max-age=5' });
    expect(res.headers.get('Cache-Control')).toBe('public, max-age=5');
  });

  it('stamps a HEAD request identically to GET (cache probes see the same header)', async () => {
    const res = await runCacheControl({ method: 'HEAD' });
    expect(res.headers.get('Cache-Control')).toBe(ANON);
  });

  it('forces private, no-store on an anonymous response that sets a cookie', async () => {
    // The whole scheme assumes anonymous responses are cookie-less. If one ever
    // carries Set-Cookie, it must never be shared-cached as `public` — that
    // would replay one visitor's session/CSRF cookie to everyone.
    const res = await runCacheControl({ setCookie: 'sessionid=leak; Path=/' });
    expect(res.headers.get('Cache-Control')).toBe('private, no-store');
  });

  it('forces private, no-store on a cookie-setting __data.json response', async () => {
    const res = await runCacheControl({
      pathname: '/titles/__data.json',
      contentType: 'application/json',
      setCookie: 'csrftoken=leak; Path=/',
    });
    expect(res.headers.get('Cache-Control')).toBe('private, no-store');
  });

  it('never sets Vary on the anonymous case', async () => {
    const res = await runCacheControl({});
    expect(res.headers.get('Vary')).toBeNull();
  });
});
