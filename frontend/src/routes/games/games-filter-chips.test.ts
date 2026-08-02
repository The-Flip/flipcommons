import { describe, expect, it } from 'vitest';
import { UNCLASSIFIED, emptyFilterState } from '$lib/filters/games';
import type { GameFilterOptionsSchema } from '$lib/api/schema';
import { gameFilterChips } from './games-filter-chips';

function options(overrides: Partial<GameFilterOptionsSchema> = {}): GameFilterOptionsSchema {
  return {
    manufacturer: [],
    person: [],
    technology_generation: [],
    display_type: [],
    system: [],
    reward_type: [],
    edge: [],
    cabinet: [],
    game_format: [],
    production_status: [],
    theme: [],
    gameplay_feature: [],
    franchise: [],
    series: [],
    player_count: [],
    ...overrides,
  };
}

describe('gameFilterChips', () => {
  it('returns no chips when nothing is filtered', () => {
    expect(gameFilterChips(emptyFilterState(), options())).toEqual([]);
  });

  it('labels a single-select chip from the option list and clears it on remove', () => {
    const filters = { ...emptyFilterState(), manufacturer: 'stern' };
    const chips = gameFilterChips(
      filters,
      options({ manufacturer: [{ public_id: 'stern', name: 'Stern', count: 3 }] }),
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'manufacturer:stern', label: 'Stern' });

    chips[0].remove();
    expect(filters.manufacturer).toBeNull();
  });

  it('falls back to the slug when the option list lacks a name', () => {
    const chips = gameFilterChips({ ...emptyFilterState(), manufacturer: 'mystery' }, options());
    expect(chips[0].label).toBe('mystery');
  });

  it('emits one chip per multi-select value and removes only that value', () => {
    const filters = { ...emptyFilterState(), themes: ['sci-fi', 'horror'] };
    const chips = gameFilterChips(
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

  it('labels edge chips from the relationship vocabulary, not the option names', () => {
    const filters = { ...emptyFilterState(), edges: ['bootleg', 'copy:in'] };
    // The payload names edge options by wire value; the chip must not echo it.
    const chips = gameFilterChips(
      filters,
      options({
        edge: [
          { public_id: 'bootleg', name: 'bootleg', count: 2 },
          { public_id: 'copy:in', name: 'copy:in', count: 1 },
        ],
      }),
    );

    expect(chips.map((c) => c.label)).toEqual(['Bootleg', 'Has been copied']);
    chips[0].remove();
    expect(filters.edges).toEqual(['copy:in']);
  });

  it('formats the player-count chip, folding 6+', () => {
    expect(gameFilterChips({ ...emptyFilterState(), playerCount: 4 }, options())[0].label).toBe(
      '4 players',
    );
    expect(gameFilterChips({ ...emptyFilterState(), playerCount: 6 }, options())[0].label).toBe(
      '6+ players',
    );
  });

  it('builds one year-range chip and clears both bounds on remove', () => {
    const filters = { ...emptyFilterState(), yearMin: 1990, yearMax: 2000 };
    const chips = gameFilterChips(filters, options());

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'year', label: 'Year: 1990–2000' });

    chips[0].remove();
    expect(filters.yearMin).toBeNull();
    expect(filters.yearMax).toBeNull();
  });

  it('shows one chip for the canonical preset pair, labeled like the dropdown selection', () => {
    const filters = { ...emptyFilterState(), gameFormats: ['pinball', UNCLASSIFIED] };
    const chips = gameFilterChips(
      filters,
      options({ game_format: [{ public_id: 'pinball', name: 'Pinball', count: 5659 }] }),
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'gameFormats:pinball', label: 'Pinball' });
    chips[0].remove();
    expect(filters.gameFormats).toEqual([]);
  });

  it('shows one chip for a lone sparse value, including unclassified', () => {
    const exact = { ...emptyFilterState(), gameFormats: ['bingo-pinball'] };
    const exactChips = gameFilterChips(
      exact,
      options({ game_format: [{ public_id: 'bingo-pinball', name: 'Bingo Pinball', count: 3 }] }),
    );
    expect(exactChips.map((c) => c.label)).toEqual(['Bingo Pinball']);

    // The reserved value's label is the frontend literal — it is never a
    // payload option to resolve a name from.
    const nulls = { ...emptyFilterState(), cabinets: [UNCLASSIFIED] };
    const nullChips = gameFilterChips(nulls, options());
    expect(nullChips.map((c) => c.label)).toEqual(['Unclassified']);
    nullChips[0].remove();
    expect(nulls.cabinets).toEqual([]);
  });

  it('degrades an arbitrary sparse union to one removable chip per raw value', () => {
    const filters = { ...emptyFilterState(), gameFormats: ['pinball', 'shuffle'] };
    const chips = gameFilterChips(
      filters,
      options({
        game_format: [
          { public_id: 'pinball', name: 'Pinball', count: 5659 },
          { public_id: 'shuffle', name: 'Shuffle', count: 40 },
        ],
      }),
    );

    expect(chips.map((c) => c.label)).toEqual(['Pinball', 'Shuffle']);
    chips[1].remove();
    expect(filters.gameFormats).toEqual(['pinball']);
  });

  it('keeps a stable order across mixed dimensions', () => {
    const filters = {
      ...emptyFilterState(),
      manufacturer: 'stern',
      themes: ['sci-fi'],
      playerCount: 4,
    };
    const chips = gameFilterChips(
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
