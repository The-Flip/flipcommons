import { asset, resolve } from '$app/paths';

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

/** Format a year_start / year_end pair as a human-readable range. */
export function formatYearRange(yearStart?: number | null, yearEnd?: number | null): string | null {
  if (yearStart && yearEnd) return `${yearStart}\u2013${yearEnd}`;
  if (yearStart) return `${yearStart}\u2013present`;
  if (yearEnd) return `\u2013${yearEnd}`;
  return null;
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
