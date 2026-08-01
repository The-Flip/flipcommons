import { describe, it, expect } from 'vitest';
import {
  emptyMfrFilterState,
  hasActiveMfrFilters,
  mfrFiltersFromParams,
  mfrFiltersToParams,
  toNum,
  type MfrFilterState,
} from './manufacturer-facet-engine';

// ---------------------------------------------------------------------------
// hasActiveMfrFilters — drives the sidebar's "Clear all"
// ---------------------------------------------------------------------------

describe('hasActiveMfrFilters', () => {
  it('is false for the empty state and for a query-only state', () => {
    expect(hasActiveMfrFilters(emptyMfrFilterState())).toBe(false);
    // `query` is deliberately excluded — the search box has its own clear control.
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), query: 'williams' })).toBe(false);
  });

  it('is true when any structured dimension is set', () => {
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), location: 'usa' })).toBe(true);
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), yearMin: 1990 })).toBe(true);
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), person: 'pat-lawlor' })).toBe(true);
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), techGeneration: 'solid-state' })).toBe(
      true,
    );
  });
});

// ---------------------------------------------------------------------------
// URL serialization round-trip (real backend field names)
// ---------------------------------------------------------------------------

describe('mfrFiltersFromParams / mfrFiltersToParams', () => {
  it('round-trips all fields', () => {
    const original: MfrFilterState = {
      query: 'test',
      location: 'usa',
      yearMin: 1990,
      yearMax: 2000,
      person: 'pat-lawlor',
      techGeneration: 'solid-state',
    };
    const sp = mfrFiltersToParams(original, new URLSearchParams());
    const restored = mfrFiltersFromParams(sp);
    expect(restored).toEqual(original);
  });

  it('serializes to the real backend field names', () => {
    const sp = mfrFiltersToParams(
      { ...emptyMfrFilterState(), location: 'usa', yearMin: 1990, techGeneration: 'solid-state' },
      new URLSearchParams(),
    );
    expect(sp.get('location')).toBe('usa');
    expect(sp.get('year_min')).toBe('1990');
    expect(sp.get('technology_generation')).toBe('solid-state');
  });

  it('empty state produces no params', () => {
    const sp = mfrFiltersToParams(emptyMfrFilterState(), new URLSearchParams());
    expect(sp.toString()).toBe('');
  });

  it('reads partial params', () => {
    const f = mfrFiltersFromParams(
      new URLSearchParams('location=usa&technology_generation=solid-state'),
    );
    expect(f.location).toBe('usa');
    expect(f.techGeneration).toBe('solid-state');
    expect(f.person).toBeNull();
  });

  it('coerces a non-finite numeric param to null (no NaN seeding)', () => {
    const f = mfrFiltersFromParams(new URLSearchParams('year_min=abc'));
    expect(f.yearMin).toBeNull();
  });
});

describe('toNum', () => {
  it('parses finite numbers and rejects blanks / non-finite input', () => {
    expect(toNum('1990')).toBe(1990);
    expect(toNum('')).toBeNull();
    expect(toNum('   ')).toBeNull();
    expect(toNum('abc')).toBeNull();
  });
});
