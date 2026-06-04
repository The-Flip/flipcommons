import { describe, it, expect } from 'vitest';
import {
  emptyFilterState,
  filtersFromParams,
  filtersToParams,
  hasActiveFilters,
  type FilterState,
} from './facet-engine';

// ---------------------------------------------------------------------------
// hasActiveFilters — any structured filter except the free-text query
// ---------------------------------------------------------------------------

describe('hasActiveFilters', () => {
  it('is false for an empty state and for a query-only filter', () => {
    expect(hasActiveFilters(emptyFilterState())).toBe(false);
    expect(hasActiveFilters({ ...emptyFilterState(), query: 'godzilla' })).toBe(false);
  });

  it('is true when any non-query dimension is set', () => {
    expect(hasActiveFilters({ ...emptyFilterState(), manufacturer: 'stern' })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilterState(), themes: ['sci-fi'] })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilterState(), yearMin: 1990 })).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// URL <-> FilterState round-trip
// ---------------------------------------------------------------------------

describe('filtersFromParams', () => {
  it('returns empty state for empty params', () => {
    const sp = new URLSearchParams();
    expect(filtersFromParams(sp)).toEqual(emptyFilterState());
  });

  it('parses all param types', () => {
    const sp = new URLSearchParams(
      'q=medieval&tech_gen=solid-state&year_min=1990&year_max=2000&manufacturer=williams&person=pat-lawlor&theme=medieval&theme=sports&display_type=dmd&player_count=4&system=wpc-95&franchise=star-wars&series=castle',
    );
    const f = filtersFromParams(sp);
    expect(f.query).toBe('medieval');
    expect(f.techGeneration).toBe('solid-state');
    expect(f.yearMin).toBe(1990);
    expect(f.yearMax).toBe(2000);
    expect(f.manufacturer).toBe('williams');
    expect(f.person).toBe('pat-lawlor');
    expect(f.themes).toEqual(['medieval', 'sports']);
    expect(f.displayType).toBe('dmd');
    expect(f.playerCount).toBe(4);
    expect(f.system).toBe('wpc-95');
    expect(f.franchise).toBe('star-wars');
    expect(f.series).toBe('castle');
  });

  it('drops non-numeric numeric params instead of seeding NaN', () => {
    // Only reachable via a hand-edited URL, but must stay consistent with
    // queryFromUrl's server-side guard so the two parsers can't diverge.
    const f = filtersFromParams(new URLSearchParams('year_min=abc&player_count='));
    expect(f.yearMin).toBeNull();
    expect(f.playerCount).toBeNull();
  });

  it('round-trips multi-value dimensions as repeated params', () => {
    const state: FilterState = {
      ...emptyFilterState(),
      themes: ['medieval', 'sports'],
      features: ['multiball'],
    };
    const sp = filtersToParams(state, new URLSearchParams());
    expect(sp.getAll('theme')).toEqual(['medieval', 'sports']);
    expect(sp.getAll('feature')).toEqual(['multiball']);
    // and back
    expect(filtersFromParams(sp).themes).toEqual(['medieval', 'sports']);
    expect(filtersFromParams(sp).features).toEqual(['multiball']);
  });
});

describe('filtersToParams', () => {
  it('produces empty params for empty state', () => {
    const sp = filtersToParams(emptyFilterState(), new URLSearchParams());
    expect(sp.toString()).toBe('');
  });

  it('round-trips through filtersFromParams', () => {
    const original: FilterState = {
      ...emptyFilterState(),
      query: 'test',
      techGeneration: 'solid-state',
      yearMin: 1990,
      themes: ['medieval', 'sports'],
      playerCount: 4,
    };
    const sp = filtersToParams(original, new URLSearchParams());
    const restored = filtersFromParams(sp);
    expect(restored).toEqual(original);
  });
});
