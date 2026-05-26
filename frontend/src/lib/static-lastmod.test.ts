import { describe, it, expect } from 'vitest';
import { STATIC_LASTMOD, formatLastUpdated } from './static-lastmod';
import { SEARCH_ENGINE_INDEXABLE_ROUTE_IDS } from './route-metadata.server';

const YYYY_MM_DD_RE = /^\d{4}-\d{2}-\d{2}$/;

// Runtime mirror of the `StaticIndexableRouteId` type. The `satisfies` clause
// in `static-lastmod.ts` already pins the typecheck-time contract; this test
// pins the same contract at runtime so the failure has a clear name (and
// catches drift if a route's classification changes without the type
// derivation noticing).
function staticIndexableRouteIds(): readonly string[] {
  return SEARCH_ENGINE_INDEXABLE_ROUTE_IDS.filter((id) => !id.includes('['));
}

describe('STATIC_LASTMOD', () => {
  it('has an entry for every static indexable route', () => {
    const expected = [...staticIndexableRouteIds()].sort();
    const actual = Object.keys(STATIC_LASTMOD).sort();
    expect(actual).toEqual(expected);
  });

  it('has no entry for a parameterized listed-indexable route', () => {
    const parameterized = Object.keys(STATIC_LASTMOD).filter((id) => id.includes('['));
    expect(parameterized).toEqual([]);
  });

  it('every value is a YYYY-MM-DD string that parses as a real calendar date', () => {
    for (const [routeId, value] of Object.entries(STATIC_LASTMOD)) {
      expect(value, `${routeId} value`).toMatch(YYYY_MM_DD_RE);
      const [y, m, d] = value.split('-').map(Number);
      const date = new Date(Date.UTC(y, m - 1, d));
      // Round-trip catches things like "2026-02-30" or "2026-13-01" — Date
      // silently rolls them over, so we detect mismatch after construction.
      expect(date.getUTCFullYear(), `${routeId} year`).toBe(y);
      expect(date.getUTCMonth() + 1, `${routeId} month`).toBe(m);
      expect(date.getUTCDate(), `${routeId} day`).toBe(d);
    }
  });
});

describe('formatLastUpdated', () => {
  it('renders YYYY-MM-DD as long-form English', () => {
    expect(formatLastUpdated('2026-04-11')).toBe('April 11, 2026');
    expect(formatLastUpdated('2026-01-01')).toBe('January 1, 2026');
    expect(formatLastUpdated('2026-12-31')).toBe('December 31, 2026');
  });

  it('throws on malformed input', () => {
    expect(() => formatLastUpdated('April 2026')).toThrow();
    expect(() => formatLastUpdated('2026/04/11')).toThrow();
    expect(() => formatLastUpdated('')).toThrow();
  });

  it('throws on a well-formed string that is not a real calendar date', () => {
    // Date.UTC silently rolls these over (Feb 30 → March 2, month 13 → next Jan).
    expect(() => formatLastUpdated('2026-02-30')).toThrow();
    expect(() => formatLastUpdated('2026-13-01')).toThrow();
    expect(() => formatLastUpdated('2026-04-31')).toThrow();
  });
});
