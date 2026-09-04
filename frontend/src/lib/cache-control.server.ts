import type { Handle, RequestEvent } from '@sveltejs/kit';
import { MODE_COOKIE_NAME, MODE_COOKIE_VALUE } from '$lib/kiosk/config';

/**
 * How long the shared edge cache (Bunny) serves an anonymous entry as fresh.
 * Expressed as `s-maxage` (shared-cache-only), never `max-age` — see ANON.
 * Tunable: the window is a product judgement (how stale a non-editing reader
 * tolerates), not load-bearing for correctness — contributors carry
 * `sessionid` and bypass the shared cache entirely.
 */
const EDGE_MAX_AGE = 60; // seconds

/** Strictest directive: never stored by any cache. Used for kiosk, for any
 * response that sets a cookie, and for every response that is not a
 * successful page or data request (errors, redirects, form-action POSTs,
 * non-page endpoints). */
const NO_STORE = 'private, no-store';

/**
 * CDN-only caching: the shared edge cache may store for `s-maxage`, but
 * `max-age=0` forces every BROWSER to revalidate on each navigation rather
 * than reuse a local copy. This closes a contributor-freshness hole: a user
 * who viewed a record while anonymous holds a `public` browser-cache entry,
 * and with no `Vary: Cookie` the browser would otherwise reuse it *after*
 * signing in — serving them a stale copy of their own just-made edit without
 * the request ever reaching the edge bypass. `max-age=0` means the post-auth
 * request always leaves the browser, carries `sessionid`, and bypasses to a
 * fresh origin render. (No browser-facing `stale-while-revalidate` for the
 * same reason — it would let the browser serve that stale copy.)
 */
const ANON = `public, s-maxage=${EDGE_MAX_AGE}, max-age=0`;
const AUTHED = 'private, no-cache';
const KIOSK = NO_STORE;

/**
 * Stamp `Cache-Control` on every SSR response that did not set its own, so
 * a shared edge cache (Bunny) can absorb anonymous traffic without ever
 * serving a contributor a stale copy of their own edit, and so nothing
 * leaves unstamped: Bunny gives an unstamped response its 30-day default.
 *
 * For a successful page or data request the directive is driven by the
 * request's COOKIES, not the route: the SSR HTML is per-user-invariant
 * (auth UI hydrates client-side), so every visitor gets identical markup
 * and only the caching directive differs. Everything else is
 * `private, no-store`; `isCacheablePage` says why each case must not be
 * cached.
 *
 * Deliberately NO `Vary: Cookie`: keying the anonymous entry on the Cookie
 * header would fragment it per-`csrftoken` (one entry per visitor) and
 * shatter the shared cache. The audience split is expressed by the
 * `public`/`private` choice plus the edge's own cookie-bypass rule.
 *
 * Responses SvelteKit answers before `handle` runs (`/_app/env.js`, static
 * files, prerendered pages) never reach this hook; the Caddyfile carries the
 * matching backstop for those.
 */
export const cacheControlHandle: Handle = async ({ event, resolve }) => {
  // Read the ORIGINAL request Cookie header, captured before `resolve()`:
  // the cache directive must reflect what the client sent, not SvelteKit's
  // post-render cookie jar — rendering can mutate it (e.g. an invalid
  // session is cleared during a load, which would hide `sessionid` from a
  // post-`resolve` `event.cookies.get`).
  const cookie = event.request.headers.get('cookie') ?? '';
  const response = await resolve(event);
  // Endpoints that set their own policy (`robots.txt`, the sitemap) keep it.
  if (!response.headers.has('Cache-Control')) {
    response.headers.set('Cache-Control', directive(event, response, cookie));
  }
  return response;
};

/** The directive for a response that set none of its own. */
function directive(event: RequestEvent, response: Response, cookie: string): string {
  if (!isCacheablePage(event, response)) return NO_STORE;
  // A response that sets a cookie must never be shared-cached. The whole
  // scheme assumes anonymous responses are cookie-less; an edge that stored
  // a `Set-Cookie` would replay one visitor's session/CSRF cookie to every
  // other visitor. Force the strictest directive — downgrading even the
  // anonymous `public` branch — so a violation of that invariant becomes a
  // safe non-cache instead of a cross-user leak. (SvelteKit surfaces any
  // `cookies.set()` from a load as a `set-cookie` header here, before
  // `handle` returns.)
  if (response.headers.has('set-cookie')) return NO_STORE;
  return directiveFor(cookie);
}

const MODE_KIOSK = new RegExp(`(?:^|;\\s*)${MODE_COOKIE_NAME}=${MODE_COOKIE_VALUE}(?:;|$)`);
const SESSION = /(?:^|;\s*)sessionid=/;

/** Kiosk (a licensing-gated audience) wins over an also-present `sessionid`,
 * since a kiosk terminal may be signed in. */
function directiveFor(cookie: string): string {
  if (MODE_KIOSK.test(cookie)) return KIOSK;
  if (SESSION.test(cookie)) return AUTHED;
  return ANON;
}

/**
 * Whether the response is a successful SSR HTML document or SvelteKit
 * `__data.json` data request — the two surfaces a visitor navigates, and
 * the only ones the cookie-driven directives apply to. Everything else is
 * `private, no-store`:
 * - non-GET/HEAD (form-action POSTs flow through `handle` too — never
 *   `public`; HEAD mirrors GET so cache probes see identical headers)
 * - non-2xx responses: 4xx/5xx (a transient 500 or a 404 for a just-created
 *   record must not be cached) AND 3xx redirects — an auth-gate redirect
 *   (`requireCapability` throws `redirect`) stamped `public` would be
 *   replayed from the browser cache after the user signs in, bouncing them
 *   off a route they're now authorized for
 * - non-page `+server.ts` endpoints (e.g. the `/__health` liveness probe):
 *   `__data.json` is detected by pathname, not content-type, because its
 *   content-type is `application/json`, indistinguishable from a JSON
 *   endpoint.
 */
function isCacheablePage(event: RequestEvent, response: Response): boolean {
  if (event.request.method !== 'GET' && event.request.method !== 'HEAD') return false;
  if (response.status < 200 || response.status >= 300) return false;
  if (event.url.pathname.endsWith('/__data.json')) return true;
  return (response.headers.get('content-type') ?? '').startsWith('text/html');
}
