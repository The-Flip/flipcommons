import { describe, expect, it } from 'vitest';

import type { FacetedTitle } from '$lib/facet-engine';
import { decideCreatePrompt } from './titles-create-prompt';

function makeTitle(overrides: Partial<FacetedTitle> = {}): FacetedTitle {
  return {
    name: 'Godzilla',
    slug: 'godzilla',
    abbreviations: [],
    model_count: 1,
    manufacturer: { public_id: 'stern', name: 'Stern' },
    year: 2021,
    thumbnail_url: null,
    tech_generations: [],
    display_types: [],
    player_counts: [],
    systems: [],
    themes: [],
    gameplay_features: [],
    reward_types: [],
    persons: [],
    franchise: null,
    series: null,
    year_min: null,
    year_max: null,
    ipdb_rating_max: null,
    ...overrides,
  };
}

describe('decideCreatePrompt', () => {
  it('hides the prompt for an empty query', () => {
    const decision = decideCreatePrompt({
      titles: [],
      query: '   ',
      isAuthenticated: true,
    });
    expect(decision.show).toBe(false);
  });

  it('hides the prompt for anonymous users even with zero matches', () => {
    const decision = decideCreatePrompt({
      titles: [],
      query: 'Unknown Title',
      isAuthenticated: false,
    });
    expect(decision.show).toBe(false);
  });

  it('shows the prompt when the query alone matches zero titles', () => {
    const decision = decideCreatePrompt({
      titles: [makeTitle({ name: 'Godzilla', slug: 'godzilla' })],
      query: 'No Such Title',
      isAuthenticated: true,
    });
    expect(decision.show).toBe(true);
    expect(decision.query).toBe('No Such Title');
  });

  it('trims whitespace from the query before returning it', () => {
    const decision = decideCreatePrompt({
      titles: [],
      query: '   Ghostbusters   ',
      isAuthenticated: true,
    });
    expect(decision.query).toBe('Ghostbusters');
  });

  it('hides the prompt when the query alone matches an existing title', () => {
    const decision = decideCreatePrompt({
      titles: [makeTitle({ name: 'Godzilla', slug: 'godzilla' })],
      query: 'Godzilla',
      isAuthenticated: true,
    });
    expect(decision.show).toBe(false);
  });

  it('ignores other facets — a faceted filter cannot create a false positive', () => {
    // A "Williams" facet would hide a real Stern-manufactured Godzilla, and
    // without this invariant the prompt would incorrectly offer to create one.
    // decideCreatePrompt only takes query + authenticated, so the facet
    // state isn't even visible to it — the invariant is structural.
    const decision = decideCreatePrompt({
      titles: [
        makeTitle({
          name: 'Godzilla',
          slug: 'godzilla-stern',
          manufacturer: { public_id: 'stern', name: 'Stern' },
        }),
      ],
      query: 'Godzilla',
      isAuthenticated: true,
    });
    expect(decision.show).toBe(false);
  });

  it('matches against abbreviations as well as names', () => {
    const decision = decideCreatePrompt({
      titles: [makeTitle({ name: 'Medieval Madness', abbreviations: ['MM'] })],
      query: 'MM',
      isAuthenticated: true,
    });
    expect(decision.show).toBe(false);
  });
});
