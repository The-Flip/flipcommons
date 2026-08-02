import { describe, it, expect } from 'vitest';
import {
  apiQueryFromUrl,
  emptyMfrFilterState,
  hasActiveMfrFilters,
  mfrFilterCodec,
  type MfrApiQuery,
  type MfrFilterState,
} from './manufacturers';

const { parse, serialize, canonical } = mfrFilterCodec;

/**
 * A state setting every field, so the round-trip below exercises every param.
 * Adding an `MfrFilterState` field makes this literal a compile error until
 * the field gets a value here; the emptiness guard keeps the value meaningful.
 */
const FULL_STATE: MfrFilterState = {
  q: 'test',
  location: 'usa',
  year_min: 1990,
  year_max: 2000,
  person: 'pat-lawlor',
  technology_generation: 'solid-state',
};

// ---------------------------------------------------------------------------
// hasActiveMfrFilters — drives the sidebar's "Clear all"
// ---------------------------------------------------------------------------

describe('hasActiveMfrFilters', () => {
  it('is false for the empty state and for a query-only state', () => {
    expect(hasActiveMfrFilters(emptyMfrFilterState())).toBe(false);
    // `q` is deliberately excluded — the search box has its own clear control.
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), q: 'williams' })).toBe(false);
  });

  it('is true when any structured dimension is set', () => {
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), location: 'usa' })).toBe(true);
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), year_min: 1990 })).toBe(true);
    expect(hasActiveMfrFilters({ ...emptyMfrFilterState(), person: 'pat-lawlor' })).toBe(true);
    expect(
      hasActiveMfrFilters({ ...emptyMfrFilterState(), technology_generation: 'solid-state' }),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// URL serialization round-trip (real backend field names)
// ---------------------------------------------------------------------------

describe('mfrFilterCodec', () => {
  it('the full state actually sets every field (guards the fixture itself)', () => {
    for (const [field, value] of Object.entries(FULL_STATE)) {
      const empty = value == null || value === '';
      expect(empty, `FULL_STATE.${field} must be set`).toBe(false);
    }
  });

  it('parse ∘ serialize is identity on the full state', () => {
    expect(parse(serialize(FULL_STATE))).toEqual(FULL_STATE);
  });

  it('serializes to the real backend field names', () => {
    const sp = serialize({
      ...emptyMfrFilterState(),
      location: 'usa',
      year_min: 1990,
      technology_generation: 'solid-state',
    });
    expect(sp.get('location')).toBe('usa');
    expect(sp.get('year_min')).toBe('1990');
    expect(sp.get('technology_generation')).toBe('solid-state');
  });

  it('empty state produces no params', () => {
    expect(serialize(emptyMfrFilterState()).toString()).toBe('');
  });

  it('reads partial params', () => {
    const f = parse(new URLSearchParams('location=usa&technology_generation=solid-state'));
    expect(f.location).toBe('usa');
    expect(f.technology_generation).toBe('solid-state');
    expect(f.person).toBeNull();
  });

  it('coerces a non-finite numeric param to null (no NaN seeding)', () => {
    const f = parse(new URLSearchParams('year_min=abc'));
    expect(f.year_min).toBeNull();
  });

  it('canonical is stable: equal states serialize to equal strings', () => {
    expect(canonical({ ...FULL_STATE })).toBe(canonical(FULL_STATE));
    expect(canonical(FULL_STATE)).not.toBe(canonical(emptyMfrFilterState()));
  });
});

// ---------------------------------------------------------------------------
// URL -> API query (the SSR reader)
// ---------------------------------------------------------------------------

describe('apiQueryFromUrl', () => {
  it('reads nothing from a bare URL', () => {
    const q = apiQueryFromUrl(new URL('http://localhost/manufacturers'));
    expect(Object.values(q).every((v) => v === undefined)).toBe(true);
  });

  it('reads the same vocabulary the codec writes', () => {
    const q = apiQueryFromUrl(new URL(`http://localhost/manufacturers?${serialize(FULL_STATE)}`));
    const expected: MfrApiQuery = {
      q: 'test',
      location: 'usa',
      person: 'pat-lawlor',
      technology_generation: 'solid-state',
      year_min: 1990,
      year_max: 2000,
    };
    expect(q).toEqual(expected);
  });

  it('coerces numbers and drops non-finite input, matching the codec', () => {
    const q = apiQueryFromUrl(new URL('http://localhost/manufacturers?year_min=1990&year_max=abc'));
    expect(q.year_min).toBe(1990);
    expect(q.year_max).toBeUndefined();
  });
});
