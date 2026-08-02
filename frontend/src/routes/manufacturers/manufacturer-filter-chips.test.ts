import { describe, expect, it } from 'vitest';
import { emptyMfrFilterState } from '$lib/filters/manufacturers';
import type { ManufacturerFilterOptionsSchema } from '$lib/api/schema';
import { manufacturerFilterChips } from './manufacturer-filter-chips';

function options(
  overrides: Partial<ManufacturerFilterOptionsSchema> = {},
): ManufacturerFilterOptionsSchema {
  return {
    location: [],
    person: [],
    technology_generation: [],
    year: { min: null, max: null },
    ...overrides,
  };
}

describe('manufacturerFilterChips', () => {
  it('returns no chips when nothing is filtered', () => {
    expect(manufacturerFilterChips(emptyMfrFilterState(), options())).toEqual([]);
  });

  it('labels a single-select chip from the option list and clears it on remove', () => {
    const filters = { ...emptyMfrFilterState(), location: 'usa' };
    const chips = manufacturerFilterChips(
      filters,
      options({ location: [{ public_id: 'usa', name: 'USA', count: 3 }] }),
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'location:usa', label: 'USA' });

    chips[0].remove();
    expect(filters.location).toBeNull();
  });

  it('falls back to the public_id when the option list lacks a name', () => {
    const chips = manufacturerFilterChips(
      { ...emptyMfrFilterState(), person: 'mystery' },
      options(),
    );
    expect(chips[0].label).toBe('mystery');
  });

  it('builds one year-range chip and clears both bounds on remove', () => {
    const filters = { ...emptyMfrFilterState(), year_min: 1990, year_max: 2000 };
    const chips = manufacturerFilterChips(filters, options());

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'year', label: 'Year: 1990–2000' });

    chips[0].remove();
    expect(filters.year_min).toBeNull();
    expect(filters.year_max).toBeNull();
  });

  it('keeps a stable order across mixed dimensions', () => {
    const filters = {
      ...emptyMfrFilterState(),
      location: 'usa',
      person: 'pat-lawlor',
      technology_generation: 'solid-state',
      year_min: 1990,
    };
    const chips = manufacturerFilterChips(
      filters,
      options({
        location: [{ public_id: 'usa', name: 'USA', count: 1 }],
        person: [{ public_id: 'pat-lawlor', name: 'Pat Lawlor', count: 1 }],
        technology_generation: [{ public_id: 'solid-state', name: 'Solid State', count: 1 }],
      }),
    );
    expect(chips.map((c) => c.key)).toEqual([
      'location:usa',
      'person:pat-lawlor',
      'technology_generation:solid-state',
      'year',
    ]);
  });
});
