import { sequence } from '@sveltejs/kit/hooks';
import * as Sentry from '@sentry/sveltekit';
import type { Handle } from '@sveltejs/kit';
import type { RouteId } from '$app/types';
import { handleServerError } from '$lib/sentry/handle-error';
import { isSearchEngineIndexable } from '$lib/route-metadata.server';
import { cacheControlHandle } from '$lib/cache-control.server';

/**
 * Emits noindex on every non-indexable route via both `X-Robots-Tag:
 * noindex` (set on the response) and `<meta name="robots" content="noindex">`
 * (string-inserted into the rendered HTML's `<head>`). Both signals are
 * needed: the header reaches crawlers on non-HTML responses where a meta
 * tag isn't possible (e.g. `__data.json` fetches for `ssr=false` routes),
 * and the meta tag survives infrastructure that strips response headers.
 */
export const noindexHandle: Handle = async ({ event, resolve }) => {
  if (!shouldIndex(event.route.id)) {
    const response = await resolve(event, {
      transformPageChunk: ({ html }) =>
        html.replace('</head>', '<meta name="robots" content="noindex" />\n</head>'),
    });
    response.headers.set('X-Robots-Tag', 'noindex');
    return response;
  }
  return resolve(event);
};

/**
 * Returns true if the route should appear in search engine indexes. Unmatched
 * URLs (`id === null`, i.e. 404s) and unclassified routes return
 * `false` so the hook stays out of the index by default.
 */
function shouldIndex(id: RouteId | null): boolean {
  if (id === null) return false;
  try {
    return isSearchEngineIndexable(id);
  } catch {
    // isSearchEngineIndexable throws on unclassified routes. Page routes
    // can't get here — route-metadata.test.ts enforces classification for
    // every +page.svelte. So an unclassified id is a +server.ts endpoint
    // (e.g. /__health) — not an HTML page, safe to default to noindex.
    return false;
  }
}

/**
 * `sentryHandle()` provides per-request scope isolation so user data from
 * request N doesn't leak into request N+1, and attaches request context to
 * events — required even though we're not tracing. (`Sentry.init` itself
 * lives in `instrumentation.server.ts`, a load-order-safe site.)
 */
export const handle = sequence(Sentry.sentryHandle(), cacheControlHandle, noindexHandle);

/**
 * We pass `handleServerError` explicitly rather than letting Sentry's
 * `defaultErrorHandler` take over — see `lib/sentry/handle-error.ts`.
 */
export const handleError = Sentry.handleErrorWithSentry(handleServerError);
