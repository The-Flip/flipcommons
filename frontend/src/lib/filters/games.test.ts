import { describe, it, expect } from 'vitest';
import {
  UNCLASSIFIED,
  apiQueryFromUrl,
  emptyFilterState,
  gameFilterCodec,
  hasActiveFilters,
  presetValues,
  sparseSelection,
  type FilterState,
  type GamesApiQuery,
} from './games';

const { parse, serialize, canonical } = gameFilterCodec;

/**
 * A state setting every field, so the round-trip below exercises every param.
 * Adding a `FilterState` field makes this literal a compile error until the
 * field gets a value here; the emptiness guard keeps the value meaningful.
 */
const FULL_STATE: FilterState = {
  q: 'medieval',
  technology_generation: 'solid-state',
  year_min: 1990,
  year_max: 2000,
  manufacturer: 'williams',
  person: 'pat-lawlor',
  theme: ['medieval', 'sports'],
  gameplay_feature: ['multiball'],
  reward_type: ['replay'],
  edge: ['copy', 'bootleg:in'],
  game_format: ['pinball', UNCLASSIFIED],
  production_status: ['produced'],
  cabinet: ['floor'],
  display_type: 'dmd',
  player_count: 4,
  system: 'wpc-95',
  franchise: 'star-wars',
  series: 'castle',
};

// ---------------------------------------------------------------------------
// hasActiveFilters — any structured filter except the free-text query
// ---------------------------------------------------------------------------

describe('hasActiveFilters', () => {
  it('is false for an empty state and for a query-only filter', () => {
    expect(hasActiveFilters(emptyFilterState())).toBe(false);
    expect(hasActiveFilters({ ...emptyFilterState(), q: 'godzilla' })).toBe(false);
  });

  it('is true when any non-query dimension is set', () => {
    expect(hasActiveFilters({ ...emptyFilterState(), manufacturer: 'stern' })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilterState(), theme: ['sci-fi'] })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilterState(), year_min: 1990 })).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// URL <-> FilterState round-trip
// ---------------------------------------------------------------------------

describe('gameFilterCodec.parse', () => {
  it('returns empty state for empty params', () => {
    expect(parse(new URLSearchParams())).toEqual(emptyFilterState());
  });

  it('parses all param types', () => {
    const sp = new URLSearchParams(
      'q=medieval&technology_generation=solid-state&year_min=1990&year_max=2000&manufacturer=williams&person=pat-lawlor&theme=medieval&theme=sports&edge=copy&edge=bootleg:in&display_type=dmd&player_count=4&system=wpc-95&franchise=star-wars&series=castle',
    );
    const f = parse(sp);
    expect(f.q).toBe('medieval');
    expect(f.technology_generation).toBe('solid-state');
    expect(f.year_min).toBe(1990);
    expect(f.year_max).toBe(2000);
    expect(f.manufacturer).toBe('williams');
    expect(f.person).toBe('pat-lawlor');
    expect(f.theme).toEqual(['medieval', 'sports']);
    expect(f.edge).toEqual(['copy', 'bootleg:in']);
    expect(f.display_type).toBe('dmd');
    expect(f.player_count).toBe(4);
    expect(f.system).toBe('wpc-95');
    expect(f.franchise).toBe('star-wars');
    expect(f.series).toBe('castle');
  });

  it('drops non-numeric numeric params instead of seeding NaN', () => {
    // Only reachable via a hand-edited URL, but must stay consistent with
    // apiQueryFromUrl's guard so the two readers can't diverge.
    const f = parse(new URLSearchParams('year_min=abc&player_count='));
    expect(f.year_min).toBeNull();
    expect(f.player_count).toBeNull();
  });

  it('round-trips multi-value dimensions as repeated params', () => {
    const state: FilterState = {
      ...emptyFilterState(),
      theme: ['medieval', 'sports'],
      gameplay_feature: ['multiball'],
      edge: ['copy', 'variant_of:in'],
    };
    const sp = serialize(state);
    expect(sp.getAll('theme')).toEqual(['medieval', 'sports']);
    expect(sp.getAll('gameplay_feature')).toEqual(['multiball']);
    expect(sp.getAll('edge')).toEqual(['copy', 'variant_of:in']);
    // and back
    expect(parse(sp).theme).toEqual(['medieval', 'sports']);
    expect(parse(sp).gameplay_feature).toEqual(['multiball']);
    expect(parse(sp).edge).toEqual(['copy', 'variant_of:in']);
  });
});

describe('gameFilterCodec.serialize', () => {
  it('produces empty params for empty state', () => {
    expect(serialize(emptyFilterState()).toString()).toBe('');
  });

  it('round-trips the sparse dimensions as repeated raw wire values', () => {
    const original: FilterState = {
      ...emptyFilterState(),
      game_format: ['pinball', UNCLASSIFIED],
      production_status: [UNCLASSIFIED],
      cabinet: ['cocktail'],
    };
    const sp = serialize(original);
    expect(sp.getAll('game_format')).toEqual(['pinball', UNCLASSIFIED]);
    expect(sp.getAll('production_status')).toEqual([UNCLASSIFIED]);
    expect(sp.getAll('cabinet')).toEqual(['cocktail']);
    expect(parse(sp)).toEqual(original);
  });
});

describe('gameFilterCodec round-trip over the full vocabulary', () => {
  it('the full state actually sets every field (guards the fixture itself)', () => {
    for (const [field, value] of Object.entries(FULL_STATE)) {
      const empty = value == null || value === '' || (Array.isArray(value) && value.length === 0);
      expect(empty, `FULL_STATE.${field} must be set`).toBe(false);
    }
  });

  it('parse ∘ serialize is identity on the full state', () => {
    expect(parse(serialize(FULL_STATE))).toEqual(FULL_STATE);
  });

  it('canonical is stable: equal states serialize to equal strings', () => {
    expect(canonical({ ...FULL_STATE })).toBe(canonical(FULL_STATE));
    expect(canonical(FULL_STATE)).not.toBe(canonical(emptyFilterState()));
  });
});

// ---------------------------------------------------------------------------
// URL -> API query (the SSR reader)
// ---------------------------------------------------------------------------

describe('apiQueryFromUrl', () => {
  it('reads nothing from a bare URL', () => {
    const q = apiQueryFromUrl(new URL('http://localhost/games'));
    expect(Object.values(q).every((v) => v === undefined)).toBe(true);
  });

  it('reads the same vocabulary the codec writes, plus the hidden dimensions', () => {
    const sp = serialize(FULL_STATE);
    sp.set('display_subtype', 'alphanumeric');
    sp.set('tag', 'classic');
    sp.set('technology_subgeneration', 'wpc');
    sp.set('corporate_entity', 'wms-industries');
    const q = apiQueryFromUrl(new URL(`http://localhost/games?${sp}`));
    const expected: GamesApiQuery = {
      q: 'medieval',
      manufacturer: 'williams',
      person: 'pat-lawlor',
      technology_generation: 'solid-state',
      display_type: 'dmd',
      system: 'wpc-95',
      franchise: 'star-wars',
      series: 'castle',
      player_count: 4,
      year_min: 1990,
      year_max: 2000,
      theme: ['medieval', 'sports'],
      gameplay_feature: ['multiball'],
      reward_type: ['replay'],
      edge: ['copy', 'bootleg:in'],
      game_format: ['pinball', UNCLASSIFIED],
      production_status: ['produced'],
      cabinet: ['floor'],
      display_subtype: 'alphanumeric',
      tag: 'classic',
      technology_subgeneration: 'wpc',
      corporate_entity: 'wms-industries',
    };
    expect(q).toEqual(expected);
  });

  it('coerces numbers and drops non-finite input, matching the codec', () => {
    const q = apiQueryFromUrl(new URL('http://localhost/games?year_min=1990&player_count=abc'));
    expect(q.year_min).toBe(1990);
    expect(q.player_count).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// The sparse dimensions: preset expansion and displayed selection
// ---------------------------------------------------------------------------

describe('presetValues', () => {
  it('widens the designated default to the preset pair', () => {
    expect(presetValues('pinball', 'pinball')).toEqual(['pinball', UNCLASSIFIED]);
    expect(presetValues('produced', 'produced')).toEqual(['produced', UNCLASSIFIED]);
    expect(presetValues('floor', 'floor')).toEqual(['floor', UNCLASSIFIED]);
  });

  it('keeps every other value exact', () => {
    expect(presetValues('pinball', 'bingo-pinball')).toEqual(['bingo-pinball']);
    expect(presetValues('pinball', UNCLASSIFIED)).toEqual([UNCLASSIFIED]);
  });

  it('stays exact while the payload (and its default) has not arrived', () => {
    expect(presetValues(undefined, 'pinball')).toEqual(['pinball']);
  });
});

describe('sparseSelection', () => {
  it('reads the canonical states', () => {
    expect(sparseSelection('pinball', [])).toBeNull();
    expect(sparseSelection('pinball', ['pinball', UNCLASSIFIED])).toBe('pinball');
    expect(sparseSelection('pinball', [UNCLASSIFIED, 'pinball'])).toBe('pinball');
    expect(sparseSelection('pinball', ['bingo-pinball'])).toBe('bingo-pinball');
    expect(sparseSelection('pinball', [UNCLASSIFIED])).toBe(UNCLASSIFIED);
  });

  it('reads a lone default as itself (hand-edited exact URL, honored until the next UI write)', () => {
    expect(sparseSelection('pinball', ['pinball'])).toBe('pinball');
  });

  it('refuses to name an arbitrary union', () => {
    expect(sparseSelection('pinball', ['pinball', 'shuffle'])).toBeNull();
    expect(sparseSelection('pinball', ['bingo-pinball', UNCLASSIFIED])).toBeNull();
    expect(sparseSelection('pinball', ['pinball', UNCLASSIFIED, 'shuffle'])).toBeNull();
  });

  it('without a default, only lone values name a selection', () => {
    expect(sparseSelection(undefined, ['pinball'])).toBe('pinball');
    expect(sparseSelection(undefined, ['pinball', UNCLASSIFIED])).toBeNull();
  });

  it('round-trips every UI write: what presetValues writes, sparseSelection reads back', () => {
    for (const slug of ['pinball', 'bingo-pinball', UNCLASSIFIED]) {
      expect(sparseSelection('pinball', presetValues('pinball', slug))).toBe(slug);
    }
  });
});
