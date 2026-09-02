/** Pin SEO-facing URLs (canonical, og:url, JSON-LD identity) to the configured public origin. */

import { building } from '$app/environment';
import { env } from '$env/dynamic/public';

/**
 * Rebase `url` onto `PUBLIC_SITE_ORIGIN`. SEO URLs must not track the
 * request host: on the server the `Host` header varies by caller (health
 * checks, direct hits on the Railway origin hostname) and prerendering has
 * no request at all, while in the browser `page.url` follows the address
 * bar. The origin's shape (bare https, no trailing slash) is validated
 * upstream, at build and deploy time.
 */
export function publicUrl(url: URL): URL {
  // Prerendered pages take their origin from `prerender.origin`, never from
  // the build machine's environment.
  if (building) return url;
  // Unset in `make dev`, where the request origin is the right answer.
  const siteOrigin = env.PUBLIC_SITE_ORIGIN?.trim();
  if (!siteOrigin) return url;
  // Concatenate rather than pass siteOrigin as a URL base: a pathname starting
  // with `//` is a network-path reference and would resolve onto its own host.
  return new URL(`${siteOrigin}${url.pathname}${url.search}`);
}

/**
 * The current page's identity for JSON-LD (`@id`, breadcrumb `item`):
 * public origin + pathname, no query or fragment. Use it instead of
 * `pageUrl.origin + pageUrl.pathname`, which reads the request host.
 */
export function pageIdentity(pageUrl: URL): string {
  const pinned = publicUrl(pageUrl);
  return pinned.origin + pinned.pathname;
}
