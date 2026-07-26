import { asset, resolve } from '$app/paths';
import type { CorporateEntityDetailSchema } from '$lib/api/schema';

/** Years within which an unknown operating status is presumed to still be producing. */
const UNKNOWN_RECENCY_YEARS = 6;

/** The three production-status values, derived from the generated schema. */
type OperatingStatus = NonNullable<CorporateEntityDetailSchema['operating_status']>;

/** Normalize text for search: strip diacritics, punctuation, and collapse whitespace. */
export function normalizeText(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '') // strip diacritics
    .replace(/[^\w\s]/g, '') // strip punctuation
    .replace(/\s+/g, ' ') // collapse whitespace
    .trim()
    .toLowerCase();
}

/** Wrapper around resolve() that accepts a plain string (for dynamic URLs). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const resolveHref = (url: string) => resolve(url as any);

/** Format a count with a singular/plural noun. `pluralize(1, 'model')` → `'1 model'`. */
export function pluralize(n: number, one: string, many?: string): string {
  return `${n} ${n === 1 ? one : (many ?? `${one}s`)}`;
}

/**
 * Format the production-year span of a manufacturer or corporate entity for display,
 * resolving the open-ended "present" marker from `operatingStatus`:
 *
 * - `ongoing` → `"{first}–present"`
 * - `ended` → closed `"{first}–{last}"`
 * - `unknown` → closed when the last model predates `UNKNOWN_RECENCY_YEARS`,
 *   else `"{first}–present"` (a recent last model is presumed to mean still producing).
 *
 * Equal first/last years collapse to a single year in the closed cases
 * (`"1985"`, not `"1985–1985"`). Returns null when the span has no anchoring
 * year — `firstYear`/`lastYear` are a coupled min/max, so both are null
 * together when there are no dated models.
 */
export function formatActiveRange(
  firstYear: number | null | undefined,
  lastYear: number | null | undefined,
  operatingStatus: OperatingStatus,
): string | null {
  if (firstYear == null || lastYear == null) return null;
  const openEnded =
    operatingStatus === 'ongoing' ||
    (operatingStatus === 'unknown' && lastYear > new Date().getFullYear() - UNKNOWN_RECENCY_YEARS);
  if (openEnded) return `${firstYear}–present`;
  if (firstYear === lastYear) return `${firstYear}`;
  return `${firstYear}–${lastYear}`;
}

/**
 * Resolve a path to a static asset bundled with the frontend (anything under
 * `static/`) to an absolute URL, for emission to metadata consumers (JSON-LD
 * `image`, OG `og:image`, sitemap image entries) that need fully-qualified
 * URLs.
 *
 * `asset()` may return a relative path when `paths.assets` isn't configured
 * (the common dev/local case); the URL constructor resolves it against the
 * current page origin and passes through absolute CDN URLs unchanged.
 *
 * Do NOT use for backend-served images (entity `photo_url`, `primary_image`,
 * etc.) — those are already absolute URLs from the API and don't need
 * transformation.
 */
export function absoluteAssetUrl(path: string, pageUrl: URL): string {
  return new URL(asset(path), pageUrl.origin).href;
}

export function websiteHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
