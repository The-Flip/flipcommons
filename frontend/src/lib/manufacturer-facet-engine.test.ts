import { describe, it, expect } from 'vitest';
import {
  filterManufacturers,
  filterManufacturersByQueryOnly,
  computeMfrFacetCounts,
  emptyMfrFilterState,
  mfrFiltersFromParams,
  mfrFiltersToParams,
  getMfrActiveFilterLabels,
  type FacetedManufacturer,
  type MfrFilterState,
} from './manufacturer-facet-engine';

// ---------------------------------------------------------------------------
// Test data factory
// ---------------------------------------------------------------------------

function makeMfr(overrides: Partial<FacetedManufacturer> = {}): FacetedManufacturer {
  return {
    name: 'Test Mfr',
    slug: 'test-mfr',
    model_count: 1,
    locations: [],
    persons: [],
    tech_generations: [],
    ...overrides,
  };
}

const williams = makeMfr({
  name: 'Williams',
  slug: 'williams',
  model_count: 50,
  search_text: 'Williams Electronic Manufacturing | Chicago | Illinois | USA',
  locations: [
    { public_id: 'chicago-illinois-usa', name: 'Chicago, Illinois, USA' },
    { public_id: 'illinois-usa', name: 'Illinois, USA' },
    { public_id: 'usa', name: 'USA' },
  ],
  year_min: 1958,
  year_max: 1999,
  persons: [
    { public_id: 'pat-lawlor', name: 'Pat Lawlor' },
    { public_id: 'steve-ritchie', name: 'Steve Ritchie' },
  ],
  tech_generations: [
    { public_id: 'electromechanical', name: 'Electromechanical' },
    { public_id: 'solid-state', name: 'Solid State' },
  ],
});

const stern = makeMfr({
  name: 'Stern',
  slug: 'stern',
  model_count: 80,
  search_text: 'Stern Pinball | Elk Grove Village | Illinois | USA',
  locations: [
    { public_id: 'elk-grove-village-illinois-usa', name: 'Elk Grove Village, Illinois, USA' },
    { public_id: 'illinois-usa', name: 'Illinois, USA' },
    { public_id: 'usa', name: 'USA' },
  ],
  year_min: 1999,
  year_max: 2025,
  persons: [{ public_id: 'steve-ritchie', name: 'Steve Ritchie' }],
  tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
});

const zaccaria = makeMfr({
  name: 'Zaccaria',
  slug: 'zaccaria',
  model_count: 30,
  search_text: 'Zaccaria | Bologna | Italy',
  locations: [
    { public_id: 'bologna-italy', name: 'Bologna, Italy' },
    { public_id: 'italy', name: 'Italy' },
  ],
  year_min: 1974,
  year_max: 1987,
  persons: [],
  tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
});

const allMfrs = [williams, stern, zaccaria];

// ---------------------------------------------------------------------------
// filterManufacturers
// ---------------------------------------------------------------------------

describe('filterManufacturers', () => {
  it('returns all when no filters active', () => {
    expect(filterManufacturers(allMfrs, emptyMfrFilterState())).toHaveLength(3);
  });

  it('filters by query', () => {
    const f = { ...emptyMfrFilterState(), query: 'williams' };
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams']);
  });

  it('filters by location', () => {
    const f = { ...emptyMfrFilterState(), location: 'italy' };
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['zaccaria']);
  });

  it('location filter matches at country level', () => {
    const f = { ...emptyMfrFilterState(), location: 'usa' };
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams', 'stern']);
  });

  it('filters by year min', () => {
    const f = { ...emptyMfrFilterState(), yearMin: 1990 };
    // Williams (1958-1999) overlaps, Stern (1999-2025) overlaps, Zaccaria (1974-1987) doesn't
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams', 'stern']);
  });

  it('filters by year max', () => {
    const f = { ...emptyMfrFilterState(), yearMax: 1980 };
    // Williams (1958-1999) overlaps, Zaccaria (1974-1987) overlaps, Stern doesn't
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams', 'zaccaria']);
  });

  it('filters by person', () => {
    const f = { ...emptyMfrFilterState(), person: 'pat-lawlor' };
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams']);
  });

  it('filters by tech generation', () => {
    const f = { ...emptyMfrFilterState(), techGeneration: 'electromechanical' };
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams']);
  });

  it('combines multiple filters', () => {
    const f: MfrFilterState = {
      ...emptyMfrFilterState(),
      location: 'usa',
      techGeneration: 'solid-state',
    };
    expect(filterManufacturers(allMfrs, f).map((m) => m.slug)).toEqual(['williams', 'stern']);
  });
});

// ---------------------------------------------------------------------------
// filterManufacturersByQueryOnly — gate for "no results → create?" prompt
// ---------------------------------------------------------------------------

describe('filterManufacturersByQueryOnly', () => {
  it('returns all when query is empty or whitespace', () => {
    expect(filterManufacturersByQueryOnly(allMfrs, '')).toHaveLength(3);
    expect(filterManufacturersByQueryOnly(allMfrs, '   ')).toHaveLength(3);
  });

  it('matches on name', () => {
    expect(filterManufacturersByQueryOnly(allMfrs, 'stern').map((m) => m.slug)).toEqual(['stern']);
  });

  it('matches on search_text (aliases / CE names / locations)', () => {
    // "Chicago" appears in Williams's search_text but not Stern's (which
    // is Elk Grove Village), so this is a single-hit match.
    expect(filterManufacturersByQueryOnly(allMfrs, 'chicago').map((m) => m.slug)).toEqual([
      'williams',
    ]);
  });

  it('ignores facet dimensions entirely — query is the only filter', () => {
    // Regression guard for the "no results → create?" prompt: facet state
    // (location, year, person, tech-gen) must not influence this helper.
    // Otherwise a user with an active year filter could search for an
    // existing brand and still see the "create duplicate?" prompt because
    // the year filter hid the match. The helper takes only the query.
    expect(filterManufacturersByQueryOnly(allMfrs, 'stern')).toHaveLength(1);
  });

  it('returns empty for genuinely novel queries', () => {
    expect(filterManufacturersByQueryOnly(allMfrs, 'no-such-brand')).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// computeMfrFacetCounts (N-1 approach)
// ---------------------------------------------------------------------------

describe('computeMfrFacetCounts', () => {
  it('counts all locations when no filters', () => {
    const counts = computeMfrFacetCounts(allMfrs, emptyMfrFilterState());
    expect(counts.location.get('usa')).toBe(2);
    expect(counts.location.get('italy')).toBe(1);
  });

  it('excludes own dimension (N-1)', () => {
    // Filter by location=italy → location counts should still include all
    // (because location dimension is excluded from location counts)
    const f = { ...emptyMfrFilterState(), location: 'italy' };
    const counts = computeMfrFacetCounts(allMfrs, f);
    expect(counts.location.get('usa')).toBe(2);
    expect(counts.location.get('italy')).toBe(1);
  });

  it('cross-dimension counts respect other filters', () => {
    // Filter by location=italy → person counts only from zaccaria (no persons)
    const f = { ...emptyMfrFilterState(), location: 'italy' };
    const counts = computeMfrFacetCounts(allMfrs, f);
    expect(counts.person.get('pat-lawlor')).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// URL serialization round-trip
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

  it('empty state produces no params', () => {
    const sp = mfrFiltersToParams(emptyMfrFilterState(), new URLSearchParams());
    expect(sp.toString()).toBe('');
  });

  it('reads partial params', () => {
    const sp = new URLSearchParams('loc=usa&gen=solid-state');
    const f = mfrFiltersFromParams(sp);
    expect(f.location).toBe('usa');
    expect(f.techGeneration).toBe('solid-state');
    expect(f.person).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// getMfrActiveFilterLabels
// ---------------------------------------------------------------------------

describe('getMfrActiveFilterLabels', () => {
  it('returns empty for no active filters', () => {
    expect(getMfrActiveFilterLabels(emptyMfrFilterState(), allMfrs)).toEqual([]);
  });

  it('includes location label', () => {
    const f = { ...emptyMfrFilterState(), location: 'usa' };
    const labels = getMfrActiveFilterLabels(f, allMfrs);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('USA');
    expect(labels[0].field).toBe('location');
  });

  it('includes year range label', () => {
    const f = { ...emptyMfrFilterState(), yearMin: 1990, yearMax: 2000 };
    const labels = getMfrActiveFilterLabels(f, allMfrs);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('Year: 1990\u20132000');
    expect(labels[0].field).toBe('yearMin');
  });

  it('includes person label with resolved name', () => {
    const f = { ...emptyMfrFilterState(), person: 'pat-lawlor' };
    const labels = getMfrActiveFilterLabels(f, allMfrs);
    expect(labels[0].label).toBe('Pat Lawlor');
  });

  it('falls back to slug when name not found', () => {
    const f = { ...emptyMfrFilterState(), person: 'unknown-person' };
    const labels = getMfrActiveFilterLabels(f, allMfrs);
    expect(labels[0].label).toBe('unknown-person');
  });
});
