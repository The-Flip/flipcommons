import { describe, expect, it } from 'vitest';
import { emptyMfrFilterState, type MfrFilterState } from '$lib/filters/manufacturers';
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

/** Records the patches the chips' remove closures request. */
function recorder() {
  const patches: Partial<MfrFilterState>[] = [];
  return { patches, apply: (p: Partial<MfrFilterState>) => patches.push(p) };
}

describe('manufacturerFilterChips', () => {
  it('returns no chips when nothing is filtered', () => {
    expect(manufacturerFilterChips(emptyMfrFilterState(), options(), () => {})).toEqual([]);
  });

  it('labels a single-select chip from the option list and clears it on remove', () => {
    const { patches, apply } = recorder();
    const chips = manufacturerFilterChips(
      { ...emptyMfrFilterState(), location: 'usa' },
      options({ location: [{ public_id: 'usa', name: 'USA', count: 3 }] }),
      apply,
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'location:usa', label: 'USA' });

    chips[0].remove();
    expect(patches).toEqual([{ location: null }]);
  });

  it('falls back to the public_id when the option list lacks a name', () => {
    const chips = manufacturerFilterChips(
      { ...emptyMfrFilterState(), person: 'mystery' },
      options(),
      () => {},
    );
    expect(chips[0].label).toBe('mystery');
  });

  it('builds one year-range chip and clears both bounds in one patch', () => {
    const { patches, apply } = recorder();
    const chips = manufacturerFilterChips(
      { ...emptyMfrFilterState(), year_min: 1990, year_max: 2000 },
      options(),
      apply,
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'year', label: 'Year: 1990–2000' });

    chips[0].remove();
    // One patch (one navigation), both bounds cleared together.
    expect(patches).toEqual([{ year_min: null, year_max: null }]);
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
      () => {},
    );
    expect(chips.map((c) => c.key)).toEqual([
      'location:usa',
      'person:pat-lawlor',
      'technology_generation:solid-state',
      'year',
    ]);
  });
});
