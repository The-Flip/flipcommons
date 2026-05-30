import { describe, it, expect } from 'vitest';
import {
  filterTitles,
  computeFacetCounts,
  emptyFilterState,
  filtersFromParams,
  filtersToParams,
  buildFacetRefOptions,
  buildSingleRefOptions,
  buildPlayerCountOptions,
  getActiveFilterLabels,
  expandTitlesWithAncestorThemes,
  type FacetedTitle,
  type FilterState,
} from './facet-engine';

// ---------------------------------------------------------------------------
// Test data factory
// ---------------------------------------------------------------------------

function makeTitle(overrides: Partial<FacetedTitle> = {}): FacetedTitle {
  return {
    name: 'Test Title',
    slug: 'test-title',
    abbreviations: ['TT'],
    model_count: 1,
    tech_generations: [],
    display_types: [],
    player_counts: [],
    systems: [],
    themes: [],
    persons: [],
    series: null,
    gameplay_features: [],
    reward_types: [],
    ...overrides,
  };
}

const medievalMadness = makeTitle({
  name: 'Medieval Madness',
  slug: 'medieval-madness',
  abbreviations: ['MM'],
  manufacturer: { public_id: 'williams', name: 'Williams' },
  year: 1997,
  tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
  display_types: [{ public_id: 'dmd', name: 'DMD' }],
  player_counts: [4],
  systems: [{ public_id: 'wpc-95', name: 'WPC-95' }],
  themes: [{ public_id: 'medieval', name: 'Medieval' }],
  persons: [{ public_id: 'pat-lawlor', name: 'Pat Lawlor' }],
  franchise: null,
  year_min: 1997,
  year_max: 1997,
  ipdb_rating_max: 8.5,
});

const mandalorian = makeTitle({
  name: 'The Mandalorian',
  slug: 'the-mandalorian',
  abbreviations: ['Mando'],
  manufacturer: { public_id: 'stern', name: 'Stern' },
  year: 2021,
  tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
  display_types: [{ public_id: 'lcd', name: 'LCD' }],
  player_counts: [4],
  systems: [{ public_id: 'spike-2', name: 'Spike 2' }],
  themes: [{ public_id: 'sci-fi', name: 'Sci-Fi' }],
  persons: [{ public_id: 'tim-sexton', name: 'Tim Sexton' }],
  franchise: { public_id: 'star-wars', name: 'Star Wars' },
  series: { public_id: 'star-wars-series', name: 'Star Wars Series' },
  year_min: 2021,
  year_max: 2021,
  ipdb_rating_max: 7.2,
});

const eightBall = makeTitle({
  name: 'Eight Ball Deluxe',
  slug: 'eight-ball-deluxe',
  abbreviations: ['EBD'],
  manufacturer: { public_id: 'bally', name: 'Bally' },
  year: 1981,
  tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
  display_types: [{ public_id: 'score-reels', name: 'Score Reels' }],
  player_counts: [4],
  themes: [
    { public_id: 'sports', name: 'Sports' },
    { public_id: 'pool', name: 'Pool' },
  ],
  persons: [{ public_id: 'george-christian', name: 'George Christian' }],
  year_min: 1981,
  year_max: 1981,
  ipdb_rating_max: 7.8,
});

const allTitles = [medievalMadness, mandalorian, eightBall];

// ---------------------------------------------------------------------------
// filterTitles
// ---------------------------------------------------------------------------

describe('filterTitles', () => {
  it('returns all titles when no filters are active', () => {
    const result = filterTitles(allTitles, emptyFilterState());
    expect(result).toHaveLength(3);
  });

  it('filters by text query (name)', () => {
    const state: FilterState = { ...emptyFilterState(), query: 'medieval' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by text query (manufacturer name)', () => {
    const state: FilterState = { ...emptyFilterState(), query: 'stern' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('the-mandalorian');
  });

  it('text query is accent-insensitive', () => {
    const titleWithAccent = makeTitle({ name: 'Théâtre', slug: 'theatre' });
    const state: FilterState = { ...emptyFilterState(), query: 'theatre' };
    const result = filterTitles([titleWithAccent], state);
    expect(result).toHaveLength(1);
  });

  it('filters by tech generation', () => {
    const em = makeTitle({
      slug: 'em-game',
      tech_generations: [{ public_id: 'electromechanical', name: 'EM' }],
    });
    const titles = [...allTitles, em];
    const state: FilterState = { ...emptyFilterState(), techGeneration: 'electromechanical' };
    const result = filterTitles(titles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('em-game');
  });

  it('filters by year range', () => {
    const state: FilterState = { ...emptyFilterState(), yearMin: 1990, yearMax: 2000 };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by yearMin only', () => {
    const state: FilterState = { ...emptyFilterState(), yearMin: 2000 };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('the-mandalorian');
  });

  it('filters by yearMax only', () => {
    const state: FilterState = { ...emptyFilterState(), yearMax: 1990 };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('eight-ball-deluxe');
  });

  it('filters by manufacturer', () => {
    const state: FilterState = { ...emptyFilterState(), manufacturer: 'williams' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by person', () => {
    const state: FilterState = { ...emptyFilterState(), person: 'pat-lawlor' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by single theme', () => {
    const state: FilterState = { ...emptyFilterState(), themes: ['medieval'] };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by multiple themes (AND logic)', () => {
    const state: FilterState = { ...emptyFilterState(), themes: ['sports', 'pool'] };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('eight-ball-deluxe');
  });

  it('theme AND logic excludes partial matches', () => {
    const state: FilterState = { ...emptyFilterState(), themes: ['sports', 'medieval'] };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(0);
  });

  it('filters by display type', () => {
    const state: FilterState = { ...emptyFilterState(), displayType: 'dmd' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by player count', () => {
    const twoPlayer = makeTitle({ slug: 'two-p', player_counts: [2] });
    const titles = [...allTitles, twoPlayer];
    const state: FilterState = { ...emptyFilterState(), playerCount: 2 };
    const result = filterTitles(titles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('two-p');
  });

  it('player count 6+ matches any count >= 6', () => {
    const sixPlayer = makeTitle({ slug: 'six-p', player_counts: [6] });
    const eightPlayer = makeTitle({ slug: 'eight-p', player_counts: [8] });
    const titles = [...allTitles, sixPlayer, eightPlayer];
    const state: FilterState = { ...emptyFilterState(), playerCount: 6 };
    const result = filterTitles(titles, state);
    expect(result).toHaveLength(2);
    expect(result.map((t) => t.slug).sort()).toEqual(['eight-p', 'six-p']);
  });

  it('filters by system', () => {
    const state: FilterState = { ...emptyFilterState(), system: 'wpc-95' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('filters by franchise', () => {
    const state: FilterState = { ...emptyFilterState(), franchise: 'star-wars' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('the-mandalorian');
  });

  it('filters by series', () => {
    const state: FilterState = { ...emptyFilterState(), series: 'star-wars-series' };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('the-mandalorian');
  });

  it('filters by minimum rating', () => {
    const state: FilterState = { ...emptyFilterState(), ratingMin: 8.0 };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });

  it('excludes titles without rating when ratingMin is set', () => {
    const noRating = makeTitle({ slug: 'no-rating' });
    const state: FilterState = { ...emptyFilterState(), ratingMin: 1.0 };
    const result = filterTitles([noRating], state);
    expect(result).toHaveLength(0);
  });

  it('combines multiple filters (AND)', () => {
    const state: FilterState = {
      ...emptyFilterState(),
      techGeneration: 'solid-state',
      manufacturer: 'williams',
    };
    const result = filterTitles(allTitles, state);
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe('medieval-madness');
  });
});

// ---------------------------------------------------------------------------
// computeFacetCounts — N-1 correctness
// ---------------------------------------------------------------------------

describe('computeFacetCounts', () => {
  it('returns counts for all titles when no filters active', () => {
    const counts = computeFacetCounts(allTitles, emptyFilterState());
    // All 3 titles are solid-state
    expect(counts.techGeneration.get('solid-state')).toBe(3);
    // Manufacturers
    expect(counts.manufacturer.get('williams')).toBe(1);
    expect(counts.manufacturer.get('stern')).toBe(1);
    expect(counts.manufacturer.get('bally')).toBe(1);
  });

  it('N-1: selected dimension still shows its own count', () => {
    // Filter to williams only — manufacturer count for williams should still be > 0
    const state: FilterState = { ...emptyFilterState(), manufacturer: 'williams' };
    const counts = computeFacetCounts(allTitles, state);
    // N-1 excludes the manufacturer filter when counting manufacturers,
    // so all manufacturers should still show counts
    expect(counts.manufacturer.get('williams')).toBe(1);
    expect(counts.manufacturer.get('stern')).toBe(1);
    expect(counts.manufacturer.get('bally')).toBe(1);
  });

  it('N-1: other dimensions reflect the active filter', () => {
    // Filter to williams only — display type counts should only reflect williams titles
    const state: FilterState = { ...emptyFilterState(), manufacturer: 'williams' };
    const counts = computeFacetCounts(allTitles, state);
    expect(counts.displayType.get('dmd')).toBe(1);
    expect(counts.displayType.get('lcd')).toBeUndefined();
    expect(counts.displayType.get('score-reels')).toBeUndefined();
  });

  it('counts themes across titles correctly', () => {
    const counts = computeFacetCounts(allTitles, emptyFilterState());
    expect(counts.theme.get('medieval')).toBe(1);
    expect(counts.theme.get('sci-fi')).toBe(1);
    expect(counts.theme.get('sports')).toBe(1);
    expect(counts.theme.get('pool')).toBe(1);
  });

  it('counts player counts correctly', () => {
    const counts = computeFacetCounts(allTitles, emptyFilterState());
    expect(counts.playerCount.get(4)).toBe(3);
  });

  it('counts franchise correctly', () => {
    const counts = computeFacetCounts(allTitles, emptyFilterState());
    expect(counts.franchise.get('star-wars')).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Option builders
// ---------------------------------------------------------------------------

describe('buildFacetRefOptions', () => {
  it('extracts unique options with counts', () => {
    const counts = new Map([
      ['solid-state', 3],
      ['electromechanical', 0],
    ]);
    const em = makeTitle({
      tech_generations: [{ public_id: 'electromechanical', name: 'EM' }],
    });
    const options = buildFacetRefOptions([...allTitles, em], (t) => t.tech_generations, counts);
    const ss = options.find((o) => o.slug === 'solid-state');
    expect(ss).toBeDefined();
    expect(ss!.count).toBe(3);
    expect(ss!.label).toBe('Solid State');
  });
});

describe('buildSingleRefOptions', () => {
  it('extracts unique single-ref options', () => {
    const counts = new Map([['star-wars', 1]]);
    const options = buildSingleRefOptions(allTitles, (t) => t.franchise, counts);
    expect(options).toHaveLength(1);
    expect(options[0].slug).toBe('star-wars');
    expect(options[0].count).toBe(1);
  });
});

describe('buildPlayerCountOptions', () => {
  it('groups 6+ together', () => {
    const counts = new Map([
      [1, 5],
      [2, 3],
      [4, 10],
      [6, 2],
      [8, 1],
    ]);
    const options = buildPlayerCountOptions(counts);
    expect(options).toHaveLength(4);
    const sixPlus = options.find((o) => o.value === 6);
    expect(sixPlus!.label).toBe('6+');
    expect(sixPlus!.count).toBe(3); // 2 + 1
  });

  it('returns zero counts for missing buckets', () => {
    const counts = new Map([[4, 5]]);
    const options = buildPlayerCountOptions(counts);
    expect(options.find((o) => o.value === 1)!.count).toBe(0);
    expect(options.find((o) => o.value === 2)!.count).toBe(0);
    expect(options.find((o) => o.value === 4)!.count).toBe(5);
    expect(options.find((o) => o.value === 6)!.count).toBe(0);
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
      'q=medieval&gen=solid-state&ymin=1990&ymax=2000&mfr=williams&person=pat-lawlor&theme=medieval,sports&display=dmd&players=4&sys=wpc-95&franchise=star-wars&series=castle&rating=7.5',
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
    expect(f.ratingMin).toBe(7.5);
  });
});

// ---------------------------------------------------------------------------
// getActiveFilterLabels
// ---------------------------------------------------------------------------

describe('getActiveFilterLabels', () => {
  it('returns empty array when no filters active', () => {
    expect(getActiveFilterLabels(emptyFilterState(), allTitles)).toEqual([]);
  });

  it('resolves tech generation slug to name', () => {
    const state = { ...emptyFilterState(), techGeneration: 'solid-state' };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('Solid State');
    expect(labels[0].field).toBe('techGeneration');
  });

  it('resolves display type slug to name', () => {
    const state = { ...emptyFilterState(), displayType: 'dmd' };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('DMD');
  });

  it('resolves manufacturer slug to name', () => {
    const state = { ...emptyFilterState(), manufacturer: 'williams' };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('Williams');
  });

  it('resolves person slug to name', () => {
    const state = { ...emptyFilterState(), person: 'pat-lawlor' };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('Pat Lawlor');
  });

  it('produces one chip per theme', () => {
    const state = { ...emptyFilterState(), themes: ['sports', 'pool'] };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(2);
    expect(labels[0].label).toBe('Sports');
    expect(labels[0].value).toBe('sports');
    expect(labels[1].label).toBe('Pool');
    expect(labels[1].value).toBe('pool');
  });

  it('formats player count with 6+ for >= 6', () => {
    const state = { ...emptyFilterState(), playerCount: 6 };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('6+ players');
  });

  it('formats player count normally for < 6', () => {
    const state = { ...emptyFilterState(), playerCount: 4 };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('4 players');
  });

  it('produces combined year range label', () => {
    const state = { ...emptyFilterState(), yearMin: 1990, yearMax: 2000 };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('Year: 1990\u20132000');
    expect(labels[0].field).toBe('yearMin');
  });

  it('produces year label for min only', () => {
    const state = { ...emptyFilterState(), yearMin: 1990 };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels[0].label).toBe('Year: 1990\u2013');
  });

  it('produces rating label', () => {
    const state = { ...emptyFilterState(), ratingMin: 7.5 };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(1);
    expect(labels[0].label).toBe('Rating \u2265 7.5');
  });

  it('falls back to raw slug when name not found', () => {
    const state = { ...emptyFilterState(), techGeneration: 'unknown-gen' };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels[0].label).toBe('unknown-gen');
  });

  it('resolves franchise and series', () => {
    const state = { ...emptyFilterState(), franchise: 'star-wars', series: 'star-wars-series' };
    const labels = getActiveFilterLabels(state, allTitles);
    expect(labels).toHaveLength(2);
    const franchiseLabel = labels.find((l) => l.field === 'franchise');
    const seriesLabel = labels.find((l) => l.field === 'series');
    expect(franchiseLabel!.label).toBe('Star Wars');
    expect(seriesLabel!.label).toBe('Star Wars Series');
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
      ratingMin: 7.5,
    };
    const sp = filtersToParams(original, new URLSearchParams());
    const restored = filtersFromParams(sp);
    expect(restored).toEqual(original);
  });
});

// ---------------------------------------------------------------------------
// Theme hierarchy expansion
// ---------------------------------------------------------------------------

describe('expandTitlesWithAncestorThemes', () => {
  const hierarchy = [
    { slug: 'sports', name: 'Sports', parent_slugs: [] },
    { slug: 'racing', name: 'Racing', parent_slugs: ['sports'] },
    { slug: 'air-racing', name: 'Air Racing', parent_slugs: ['sports', 'racing'] },
    { slug: 'medieval', name: 'Medieval', parent_slugs: [] },
  ];

  it('adds ancestor themes to titles', () => {
    const titles = [
      makeTitle({
        slug: 'air-race-pin',
        themes: [{ public_id: 'air-racing', name: 'Air Racing' }],
      }),
    ];
    const expanded = expandTitlesWithAncestorThemes(titles, hierarchy);
    const slugs = expanded[0].themes.map((t) => t.public_id).sort();
    expect(slugs).toEqual(['air-racing', 'racing', 'sports']);
  });

  it('does not duplicate themes already present', () => {
    const titles = [
      makeTitle({
        slug: 'sport-pin',
        themes: [
          { public_id: 'air-racing', name: 'Air Racing' },
          { public_id: 'sports', name: 'Sports' },
        ],
      }),
    ];
    const expanded = expandTitlesWithAncestorThemes(titles, hierarchy);
    const slugs = expanded[0].themes.map((t) => t.public_id).sort();
    expect(slugs).toEqual(['air-racing', 'racing', 'sports']);
  });

  it('leaves titles with no themes unchanged', () => {
    const titles = [makeTitle({ slug: 'no-theme', themes: [] })];
    const expanded = expandTitlesWithAncestorThemes(titles, hierarchy);
    expect(expanded[0].themes).toEqual([]);
  });

  it('returns original titles when hierarchy is empty', () => {
    const titles = [makeTitle({ themes: [{ public_id: 'medieval', name: 'Medieval' }] })];
    const expanded = expandTitlesWithAncestorThemes(titles, []);
    expect(expanded).toBe(titles);
  });

  it('makes parent theme filter match titles with child themes', () => {
    const titles = [
      makeTitle({
        slug: 'air-race-pin',
        themes: [{ public_id: 'air-racing', name: 'Air Racing' }],
      }),
      makeTitle({
        slug: 'medieval-pin',
        themes: [{ public_id: 'medieval', name: 'Medieval' }],
      }),
    ];
    const expanded = expandTitlesWithAncestorThemes(titles, hierarchy);
    const filtered = filterTitles(expanded, {
      ...emptyFilterState(),
      themes: ['sports'],
    });
    expect(filtered.map((t) => t.slug)).toEqual(['air-race-pin']);
  });
});
