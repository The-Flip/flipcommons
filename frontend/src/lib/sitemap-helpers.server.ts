/**
 * Helpers for the `/sitemap.xml` endpoint, split out for unit-testability.
 *
 * Server-only: {@link sitemapEtag} hashes through `node:crypto`. Still no
 * SvelteKit-runtime imports, so vitest can import the module without spinning
 * up `$env/dynamic/private` or `import.meta.glob`.
 */

import { createHash } from 'node:crypto';

/**
 * Max `<url>` entries per sitemap page (the sitemaps.org limit). Above it,
 * `/sitemap.xml` becomes a `<sitemapindex>` over `/sitemap1.xml`,
 * `/sitemap2.xml`, … subpages of at most this many entries each.
 */
export const MAX_URLS_PER_PAGE = 50_000;

/**
 * Strip `(group)` segments from a SvelteKit route ID to produce the URL
 * SvelteKit actually serves. `/(legal)/privacy` → `/privacy`.
 */
export function stripRouteGroups(routeId: string): string {
  const stripped = routeId.replaceAll(/\/\([^)]+\)/g, '');
  return stripped === '' ? '/' : stripped;
}

/**
 * A dynamic route split at its public-id param segment, ready to emit one
 * URL per slug as `prefix + slug + suffix` — e.g.
 * `/titles/[slug]/edit-history` → `{ prefix: '/titles/', suffix: '/edit-history' }`.
 */
export interface RouteSlugSlot {
  prefix: string;
  suffix: string;
}

/**
 * Split a (group-stripped) route ID at its `[slug]` / `[...path]` segment.
 *
 * Returns `null` when the route has no such segment, or has more than one
 * dynamic segment — either way the caller can't fill it from a single slug.
 * `[...path]` values ("a/b/c") substitute with literal slashes, which is
 * exactly what the Location rest route needs.
 */
export function splitRouteAtParam(routeId: string): RouteSlugSlot | null {
  const match = /\[(?:slug|\.\.\.path)\]/.exec(routeId);
  if (!match) return null;
  const prefix = routeId.slice(0, match.index);
  const suffix = routeId.slice(match.index + match[0].length);
  if (prefix.includes('[') || suffix.includes('[')) return null;
  return { prefix, suffix };
}

/**
 * Escape a value for an XML text node. Only `&`, `<` and `>` need escaping
 * in text content; sitemap `<loc>`/`<lastmod>` values never carry quotes
 * into attribute position.
 */
export function escapeXmlText(value: string): string {
  return value.replaceAll(/[&<>]/g, (character) =>
    character === '&' ? '&amp;' : character === '<' ? '&lt;' : '&gt;',
  );
}

/** Render one `<url>` element. `lastmod` is omitted when undefined. */
export function urlElement(loc: string, lastmod: string | undefined): string {
  let element = `\n  <url>\n    <loc>${escapeXmlText(loc)}</loc>\n`;
  if (lastmod) element += `    <lastmod>${escapeXmlText(lastmod)}</lastmod>\n`;
  return element + '  </url>';
}

/** Wrap pre-rendered `<url>` elements (from {@link urlElement}) in a `<urlset>` document. */
export function renderUrlset(urlElements: readonly string[]): string {
  return `<?xml version="1.0" encoding="UTF-8" ?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urlElements.join(
    '',
  )}\n</urlset>`;
}

/** Render the `<sitemapindex>` document pointing at `/sitemap1.xml` … `/sitemap{pageCount}.xml`. */
export function renderSitemapIndex(origin: string, pageCount: number): string {
  let body = `<?xml version="1.0" encoding="UTF-8" ?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`;
  for (let page = 1; page <= pageCount; page++) {
    body += `\n  <sitemap>\n    <loc>${escapeXmlText(`${origin}/sitemap${page}.xml`)}</loc>\n  </sitemap>`;
  }
  return body + '\n</sitemapindex>';
}

/**
 * A weak `ETag` over a rendered sitemap document, for conditional requests.
 *
 * Weak (`W/`) rather than strong because the bytes a client receives are not
 * necessarily the bytes hashed here — Caddy and Bunny may compress the body,
 * and a strong tag is a promise about an exact octet sequence. `If-None-Match`
 * only ever uses weak comparison, so the distinction costs nothing.
 *
 * Hashing the body, rather than deriving a timestamp from the feed, is what
 * makes the validator sound: every change to the document changes the tag,
 * including the changes no `lastmod` moves — a record soft-deleted out of a
 * feed, a detail URL newly excluded as non-canonical, a static route added by
 * a deploy, a page boundary shifting under pagination.
 */
export function sitemapEtag(body: string): string {
  return `W/"${createHash('sha256').update(body).digest('base64url')}"`;
}

/** Strip a weak-validator prefix, so `W/"abc"` and `"abc"` compare equal. */
function opaqueTag(etag: string): string {
  return etag.startsWith('W/') ? etag.slice(2) : etag;
}

/**
 * Does an `If-None-Match` request header already match `etag`?
 *
 * Weak comparison per RFC 9110 §8.8.3.2 — the `W/` prefix is ignored on both
 * sides, so the tag still matches if an intermediary weakened it. The field is
 * a comma-separated list and any member matching is a match; `*` matches any
 * existing representation.
 *
 * Splitting on `,` is a simplification — RFC 9110's `etagc` allows a comma
 * inside a quoted tag. It cannot bite here, since {@link sitemapEtag} emits
 * base64url, and it fails safe regardless: an unparsed tag simply misses and
 * the body is served.
 */
export function ifNoneMatchSatisfied(header: string | null, etag: string): boolean {
  if (!header) return false;
  const wanted = opaqueTag(etag);
  return header
    .split(',')
    .map((candidate) => candidate.trim())
    .some((candidate) => candidate === '*' || opaqueTag(candidate) === wanted);
}
