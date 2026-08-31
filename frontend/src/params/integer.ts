import type { ParamMatcher } from '@sveltejs/kit';

/**
 * SvelteKit param matcher for positive integers (no leading zeros) —
 * enables route shapes like `sitemap[[page=integer]].xml`. Without a
 * matcher, the optional `[[page]]` segment would accept arbitrary strings
 * (e.g. `/sitemapfoo.xml`).
 *
 * `/sitemap0.xml` and `/sitemap007.xml` 404 at the router (route doesn't
 * exist), so a handler receiving `page` may `Number()` it directly — the
 * only page error left to handle downstream is out-of-range.
 */
export const match: ParamMatcher = (param) => /^[1-9]\d*$/.test(param);
