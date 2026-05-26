/**
 * Hand-maintained `lastmod` dates for static, search-engine-indexable pages.
 *
 * Two consumers:
 *
 *  1. `<LastUpdated />` on the legal pages — surfaces the date to the reader.
 *  2. The `/sitemap.xml` endpoint (per `docs/plans/seo/Sitemap.md`) — emits as
 *     `<lastmod>` per page.
 *
 * Single source of truth means the user-visible date and the crawler-visible
 * `<lastmod>` cannot disagree. When a page's content changes substantively,
 * bump the date in the same diff; the legal pages display the date under
 * their `<h1>`, so a forgotten bump is visible in human review.
 *
 * Date-only `YYYY-MM-DD` is a valid `<lastmod>` per sitemaps.org — no fake
 * time component.
 *
 * Completeness (every static indexable route has an entry) is enforced at
 * test time by `static-lastmod.test.ts` rather than at typecheck time — that
 * keeps this file decoupled from `route-metadata.server.ts` and avoids
 * pulling server-only modules into the client bundle for a type derivation
 * that would otherwise need an `import type` cross-boundary hack.
 */

import type { RouteId } from '$app/types';

/**
 * Hand-maintained `YYYY-MM-DD` dates for static indexable pages.
 *
 * `satisfies Partial<Record<RouteId, string>>` rejects typos in route IDs at
 * build time (and `as const` narrows the type so each call site's key is
 * checked against the literal keys, not a wider `RouteId` index signature).
 * The completeness check — that every static indexable route has an entry —
 * lives in `static-lastmod.test.ts`.
 */
export const STATIC_LASTMOD = {
  '/': '2026-05-26',
  '/about': '2026-05-26',
  '/about/people': '2026-05-20',
  '/(legal)/privacy': '2026-05-26',
  '/(legal)/terms': '2026-05-26',
  '/(legal)/licensing': '2026-05-26',
} as const satisfies Partial<Record<RouteId, string>>;

const YYYY_MM_DD_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Render a `YYYY-MM-DD` string as a long-form English date (e.g.
 * `"2026-04-11"` → `"April 11, 2026"`).
 *
 * Locale is pinned to `en-US` rather than the runtime default: this string is
 * compared against the sitemap `<lastmod>` and against itself across renders,
 * so format stability matters more than locale negotiation. Parses as UTC to
 * avoid the day-shifting back to the prior calendar day in negative-UTC
 * zones. Throws on input that isn't a real calendar date — defensive so
 * non-`STATIC_LASTMOD` callers can't silently render nonsense like
 * `"2026-02-30"` rolled over to March.
 */
export function formatLastUpdated(yyyyMmDd: string): string {
  const m = YYYY_MM_DD_RE.exec(yyyyMmDd);
  if (!m) throw new Error(`Invalid YYYY-MM-DD date: ${yyyyMmDd}`);
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  // Round-trip: catches Feb-30, month 13, day 32, etc. `Date.UTC` silently
  // normalizes those, so the only way to detect a bad input is to read back
  // the components and compare.
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() + 1 !== month ||
    date.getUTCDate() !== day
  ) {
    throw new Error(`Not a real calendar date: ${yyyyMmDd}`);
  }
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}
