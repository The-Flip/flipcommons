/**
 * The site's name: body copy, the nav wordmark, og:site_name, and the WebSite
 * JSON-LD node. Google wants a concise, commonly-recognized name here — long
 * ones get truncated on narrow devices — so this is the form used anywhere the
 * site is being named rather than titled.
 */
export const SITE_NAME = 'Flipcommons';

/**
 * The descriptive long form, used for browser tab titles and the home page's
 * <title> and <h1>. Google reads those as supporting signals for the site name
 * but not as the name itself, which is SITE_NAME.
 */
export const SITE_TITLE = 'Flipcommons Pinball Encyclopedia';

/**
 * Shared responsive breakpoints (in rem). Defined in `breakpoints.js` so
 * `svelte.config.js` can import the same values it injects into the CSS
 * `@custom-media` declarations.
 *
 * - NARROW_BREAKPOINT: viewport is narrow; tighten up.
 * - WIDE_BREAKPOINT: viewport is wide; room for the two-column layout.
 */
export { NARROW_BREAKPOINT, WIDE_BREAKPOINT } from './breakpoints.js';

/** Build a browser tab title like "Manufacturers — Flipcommons Pinball Encyclopedia". */
export const pageTitle = (name: string) => `${name} — ${SITE_TITLE}`;

/**
 * Minimum trimmed query length the global `/search` page acts on. Below this the
 * page shows a "type at least N characters" hint and skips the request. Mirrors
 * the backend's own floor (`_MIN_SEARCH_CHARS`), which stays the source of truth
 * and returns empty sections below it regardless.
 */
export const MIN_SEARCH_QUERY_LENGTH = 3;
