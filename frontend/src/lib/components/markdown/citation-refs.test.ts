import { describe, it, expect } from 'vitest';
import type { InlineCitation } from './citation-tooltip';
import { deduplicateCitations, buildCitationMap } from './citation-refs';

const makeCitation = (
  overrides: Partial<InlineCitation> & { id: number; index: number },
): InlineCitation => ({
  source_name: 'Source',
  source_type: 'book',
  author: 'Author',
  year: 2000,
  locator: '',
  links: [],
  ...overrides,
});

// ── deduplicateCitations ──────────────────────────────────

describe('deduplicateCitations', () => {
  it('returns one entry per unique index', () => {
    const citations = [
      makeCitation({ id: 1, index: 1 }),
      makeCitation({ id: 2, index: 2 }),
      makeCitation({ id: 3, index: 1 }), // duplicate index
    ];
    const result = deduplicateCitations(citations);
    expect(result).toHaveLength(2);
    expect(result[0].index).toBe(1);
    expect(result[1].index).toBe(2);
  });

  it('preserves first-appearance order', () => {
    const citations = [
      makeCitation({ id: 10, index: 3 }),
      makeCitation({ id: 20, index: 1 }),
      makeCitation({ id: 30, index: 2 }),
    ];
    const result = deduplicateCitations(citations);
    expect(result.map((c) => c.index)).toEqual([3, 1, 2]);
  });

  it('returns empty array for empty input', () => {
    expect(deduplicateCitations([])).toEqual([]);
  });
});

// ── buildCitationMap ──────────────────────────────────────

describe('buildCitationMap', () => {
  it('maps id to CitationInfo', () => {
    const citations = [
      makeCitation({ id: 1, index: 1, source_name: 'Book A' }),
      makeCitation({ id: 2, index: 2, source_name: 'Book B' }),
    ];
    const map = buildCitationMap(citations);
    expect(map.size).toBe(2);
    expect(map.get(1)?.source_name).toBe('Book A');
    expect(map.get(2)?.source_name).toBe('Book B');
  });

  it('returns empty map for empty input', () => {
    expect(buildCitationMap([]).size).toBe(0);
  });
});
