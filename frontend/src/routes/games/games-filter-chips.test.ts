import { describe, expect, it } from 'vitest';
import { UNCLASSIFIED, emptyFilterState, type FilterState } from '$lib/filters/games';
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
    tag: [],
    cabinet: { options: [], default_slug: 'floor' },
    game_format: { options: [], default_slug: 'pinball' },
    production_status: { options: [], default_slug: 'produced' },
    theme: [],
    gameplay_feature: [],
    franchise: [],
    series: [],
    player_count: [],
    ...overrides,
  };
}

/** Records the patches the chips' remove closures request. */
function recorder() {
  const patches: Partial<FilterState>[] = [];
  return { patches, apply: (p: Partial<FilterState>) => patches.push(p) };
}

describe('gameFilterChips', () => {
  it('returns no chips when nothing is filtered', () => {
    expect(gameFilterChips(emptyFilterState(), options(), () => {})).toEqual([]);
  });

  it('labels a single-select chip from the option list and clears it on remove', () => {
    const { patches, apply } = recorder();
    const chips = gameFilterChips(
      { ...emptyFilterState(), manufacturer: 'stern' },
      options({ manufacturer: [{ public_id: 'stern', name: 'Stern', count: 3 }] }),
      apply,
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'manufacturer:stern', label: 'Stern' });

    chips[0].remove();
    expect(patches).toEqual([{ manufacturer: null }]);
  });

  it('falls back to the slug when the option list lacks a name', () => {
    const chips = gameFilterChips(
      { ...emptyFilterState(), manufacturer: 'mystery' },
      options(),
      () => {},
    );
    expect(chips[0].label).toBe('mystery');
  });

  it('emits one chip per multi-select value and removes only that value', () => {
    const { patches, apply } = recorder();
    const chips = gameFilterChips(
      { ...emptyFilterState(), theme: ['sci-fi', 'horror'] },
      options({
        theme: [
          { public_id: 'sci-fi', name: 'Sci-Fi', count: 2 },
          { public_id: 'horror', name: 'Horror', count: 1 },
        ],
      }),
      apply,
    );

    expect(chips.map((c) => c.label)).toEqual(['Sci-Fi', 'Horror']);
    chips[0].remove();
    expect(patches).toEqual([{ theme: ['horror'] }]);
  });

  it('labels edge chips from the relationship vocabulary, not the option names', () => {
    const { patches, apply } = recorder();
    // The payload names edge options by wire value; the chip must not echo it.
    const chips = gameFilterChips(
      { ...emptyFilterState(), edge: ['bootleg', 'copy:in'] },
      options({
        edge: [
          { public_id: 'bootleg', name: 'bootleg', count: 2 },
          { public_id: 'copy:in', name: 'copy:in', count: 1 },
        ],
      }),
      apply,
    );

    expect(chips.map((c) => c.label)).toEqual(['Bootleg', 'Has been copied']);
    chips[0].remove();
    expect(patches).toEqual([{ edge: ['copy:in'] }]);
  });

  it('formats the player-count chip, folding 6+', () => {
    expect(
      gameFilterChips({ ...emptyFilterState(), player_count: 4 }, options(), () => {})[0].label,
    ).toBe('4 players');
    expect(
      gameFilterChips({ ...emptyFilterState(), player_count: 6 }, options(), () => {})[0].label,
    ).toBe('6+ players');
  });

  it('builds one year-range chip and clears both bounds in one patch', () => {
    const { patches, apply } = recorder();
    const chips = gameFilterChips(
      { ...emptyFilterState(), year_min: 1990, year_max: 2000 },
      options(),
      apply,
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'year', label: 'Year: 1990–2000' });

    chips[0].remove();
    // One patch (one navigation), both bounds cleared together.
    expect(patches).toEqual([{ year_min: null, year_max: null }]);
  });

  it('shows one chip for the canonical preset pair, labeled like the dropdown selection', () => {
    const { patches, apply } = recorder();
    const chips = gameFilterChips(
      { ...emptyFilterState(), game_format: ['pinball', UNCLASSIFIED] },
      options({
        game_format: {
          options: [{ public_id: 'pinball', name: 'Pinball', count: 5659 }],
          default_slug: 'pinball',
        },
      }),
      apply,
    );

    expect(chips).toHaveLength(1);
    expect(chips[0]).toMatchObject({ key: 'game_format:pinball', label: 'Pinball' });
    chips[0].remove();
    expect(patches).toEqual([{ game_format: [] }]);
  });

  it('shows one chip for a lone sparse value, including unclassified', () => {
    const exactChips = gameFilterChips(
      { ...emptyFilterState(), game_format: ['bingo-pinball'] },
      options({
        game_format: {
          options: [{ public_id: 'bingo-pinball', name: 'Bingo Pinball', count: 3 }],
          default_slug: 'pinball',
        },
      }),
      () => {},
    );
    expect(exactChips.map((c) => c.label)).toEqual(['Bingo Pinball']);

    // The reserved value's label is the frontend literal — it is never a
    // payload option to resolve a name from.
    const { patches, apply } = recorder();
    const nullChips = gameFilterChips(
      { ...emptyFilterState(), cabinet: [UNCLASSIFIED] },
      options(),
      apply,
    );
    expect(nullChips.map((c) => c.label)).toEqual(['Unclassified']);
    nullChips[0].remove();
    expect(patches).toEqual([{ cabinet: [] }]);
  });

  it('degrades an arbitrary sparse union to one removable chip per raw value', () => {
    const { patches, apply } = recorder();
    const chips = gameFilterChips(
      { ...emptyFilterState(), game_format: ['pinball', 'shuffle'] },
      options({
        game_format: {
          options: [
            { public_id: 'pinball', name: 'Pinball', count: 5659 },
            { public_id: 'shuffle', name: 'Shuffle', count: 40 },
          ],
          default_slug: 'pinball',
        },
      }),
      apply,
    );

    expect(chips.map((c) => c.label)).toEqual(['Pinball', 'Shuffle']);
    chips[1].remove();
    expect(patches).toEqual([{ game_format: ['pinball'] }]);
  });

  it('keeps a stable order across mixed dimensions', () => {
    const filters = {
      ...emptyFilterState(),
      manufacturer: 'stern',
      theme: ['sci-fi'],
      player_count: 4,
    };
    const chips = gameFilterChips(
      filters,
      options({
        manufacturer: [{ public_id: 'stern', name: 'Stern', count: 1 }],
        theme: [{ public_id: 'sci-fi', name: 'Sci-Fi', count: 1 }],
      }),
      () => {},
    );
    expect(chips.map((c) => c.key)).toEqual([
      'manufacturer:stern',
      'theme:sci-fi',
      'player_count:4',
    ]);
  });

  it('labels chip-only dimensions with the dimension name and raw slug, and clears on remove', () => {
    const { patches, apply } = recorder();
    const chips = gameFilterChips(
      {
        ...emptyFilterState(),
        display_subtype: 'alphanumeric',
        technology_subgeneration: 'wpc',
        corporate_entity: 'wms-industries',
      },
      options(),
      apply,
    );

    expect(chips.map((c) => c.label)).toEqual([
      'Display subtype: alphanumeric',
      'Technology subgeneration: wpc',
      'Corporate entity: wms-industries',
    ]);

    chips[1].remove();
    expect(patches).toEqual([{ technology_subgeneration: null }]);
  });

  it('builds every chip without the facet payload, degrading labels to raw slugs', () => {
    const { patches, apply } = recorder();
    // The chip row is the only removal affordance for chip-only dimensions, so
    // it must not depend on the streamed (and failable) facet payload.
    const chips = gameFilterChips(
      {
        ...emptyFilterState(),
        manufacturer: 'stern',
        game_format: ['bingo-pinball'],
        tag: 'widebody',
        display_subtype: 'alphanumeric',
      },
      undefined,
      apply,
    );

    expect(chips.map((c) => c.label)).toEqual([
      'stern',
      'bingo-pinball',
      'widebody',
      'Display subtype: alphanumeric',
    ]);
    chips[0].remove();
    expect(patches).toEqual([{ manufacturer: null }]);
  });

  it('represents every dimension: a full state leaves no field without a chip', () => {
    // The builder enumerates fields by hand, so the compiler can't force a new
    // dimension to grow a chip — this fixture can: the `FilterState` type makes
    // it a compile error to omit the new field, and the loop below fails until
    // the builder emits a chip for it.
    const fullState: FilterState = {
      q: 'medieval',
      technology_generation: 'solid-state',
      year_min: 1990,
      year_max: 2000,
      manufacturer: 'williams',
      person: 'pat-lawlor',
      theme: ['medieval'],
      gameplay_feature: ['multiball'],
      reward_type: ['replay'],
      edge: ['copy'],
      game_format: ['bingo-pinball'],
      production_status: ['produced'],
      cabinet: ['cocktail'],
      display_type: 'dmd',
      player_count: 4,
      system: 'wpc-95',
      franchise: 'star-wars',
      series: 'castle',
      display_subtype: 'alphanumeric',
      tag: 'widebody',
      technology_subgeneration: 'wpc',
      corporate_entity: 'wms-industries',
    };
    const keys = gameFilterChips(fullState, options(), () => {}).map((c) => c.key);

    for (const field of Object.keys(fullState)) {
      if (field === 'q') continue; // the search box, not a chip
      const covered =
        field === 'year_min' || field === 'year_max'
          ? keys.includes('year')
          : keys.some((k) => k.startsWith(`${field}:`));
      expect(covered, `no chip for ${field}`).toBe(true);
    }
  });
});
