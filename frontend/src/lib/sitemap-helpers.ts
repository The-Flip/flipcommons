/**
 * Helpers for the `/sitemap.xml` endpoint, split out for unit-testability.
 * No SvelteKit-runtime imports here so vitest can import without spinning
 * up `$env/dynamic/private` or `import.meta.glob`.
 */

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
