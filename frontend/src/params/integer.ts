import type { ParamMatcher } from '@sveltejs/kit';

/**
 * SvelteKit param matcher for positive integers (no leading zeros) —
 * enables route shapes like `sitemap[[page=integer]].xml`. Without a
 * matcher, the optional `[[page]]` rest segment would accept arbitrary
 * strings (e.g. `/sitemapfoo.xml`), which super-sitemap can't render.
 *
 * Pattern mirrors super-sitemap's own page-validation regex (sitemap.js:105):
 * `/sitemap0.xml` and `/sitemap007.xml` should 404 at the router (route
 * doesn't exist) rather than route through and get rejected with 400
 * downstream.
 */
export const match: ParamMatcher = (param) => /^[1-9]\d*$/.test(param);
