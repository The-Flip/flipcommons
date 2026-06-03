import { describe, expect, it } from 'vitest';
import { emptyFilterState } from '$lib/facet-engine';
import type { FilterOptionsSchema } from '$lib/api/schema';
import { titleFilterChips } from './titles-filter-chips';

function options(overrides: Partial<FilterOptionsSchema> = {}): FilterOptionsSchema {
  return {
    manufacturer: [],
    person: [],
    tech_gen: [],
    display_type: [],
    system: [],
    reward_type: [],
    theme: [],
    feature: [],
    franchise: [],
    series: [],
    player_count: [],
    year: { min: null, max: null },
    ...overrides,
  };
}

describe('titleFilterChips', () => {
  it('returns no chips when nothing is filtered', () => {
    expect(titleFilterChips(emptyFilterState(), options())).toEqual([]);
  });

  it('labels a single-select chip from the option list and clears it on remove', () => {
    const filters = { ...emptyFilterState(), manufacturer: 'stern' };
    const chips = titleFilterChips(
      filters,
      options({ manufacturer: [{ public_id: 'stern', name: 'Stern', count: 3 }] }),
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'manufacturer:stern', label: 'Stern' });

    chips[0].remove();
    expect(filters.manufacturer).toBeNull();
  });

  it('falls back to the slug when the option list lacks a name', () => {
    const chips = titleFilterChips({ ...emptyFilterState(), manufacturer: 'mystery' }, options());
    expect(chips[0].label).toBe('mystery');
  });

  it('emits one chip per multi-select value and removes only that value', () => {
    const filters = { ...emptyFilterState(), themes: ['sci-fi', 'horror'] };
    const chips = titleFilterChips(
      filters,
      options({
        theme: [
          { public_id: 'sci-fi', name: 'Sci-Fi', count: 2 },
          { public_id: 'horror', name: 'Horror', count: 1 },
        ],
      }),
    );

    expect(chips.map((c) => c.label)).toEqual(['Sci-Fi', 'Horror']);
    chips[0].remove();
    expect(filters.themes).toEqual(['horror']);
  });

  it('formats the player-count chip, folding 6+', () => {
    expect(titleFilterChips({ ...emptyFilterState(), playerCount: 4 }, options())[0].label).toBe(
      '4 players',
    );
    expect(titleFilterChips({ ...emptyFilterState(), playerCount: 6 }, options())[0].label).toBe(
      '6+ players',
    );
  });

  it('builds one year-range chip and clears both bounds on remove', () => {
    const filters = { ...emptyFilterState(), yearMin: 1990, yearMax: 2000 };
    const chips = titleFilterChips(filters, options());

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'year', label: 'Year: 1990–2000' });

    chips[0].remove();
    expect(filters.yearMin).toBeNull();
    expect(filters.yearMax).toBeNull();
  });

  it('keeps a stable order across mixed dimensions', () => {
    const filters = {
      ...emptyFilterState(),
      manufacturer: 'stern',
      themes: ['sci-fi'],
      playerCount: 4,
    };
    const chips = titleFilterChips(
      filters,
      options({
        manufacturer: [{ public_id: 'stern', name: 'Stern', count: 1 }],
        theme: [{ public_id: 'sci-fi', name: 'Sci-Fi', count: 1 }],
      }),
    );
    expect(chips.map((c) => c.key)).toEqual([
      'manufacturer:stern',
      'themes:sci-fi',
      'playerCount:4',
    ]);
  });
});
