import { describe, expect, it } from 'vitest';

import { decideCreatePrompt } from './titles-create-prompt';

describe('decideCreatePrompt', () => {
  it('hides the prompt for an empty query', () => {
    const decision = decideCreatePrompt({
      query: '   ',
      isAuthenticated: true,
      queryCount: 0,
    });
    expect(decision.show).toBe(false);
  });

  it('hides the prompt for anonymous users even with zero results', () => {
    const decision = decideCreatePrompt({
      query: 'Unknown Title',
      isAuthenticated: false,
      queryCount: 0,
    });
    expect(decision.show).toBe(false);
  });

  it('shows the prompt when the query-only count is zero', () => {
    const decision = decideCreatePrompt({
      query: 'No Such Title',
      isAuthenticated: true,
      queryCount: 0,
    });
    expect(decision.show).toBe(true);
    expect(decision.query).toBe('No Such Title');
  });

  it('hides the prompt when the query matches an existing title', () => {
    const decision = decideCreatePrompt({
      query: 'Godzilla',
      isAuthenticated: true,
      queryCount: 3,
    });
    expect(decision.show).toBe(false);
  });

  it('hides the prompt while the query-only count is still streaming', () => {
    // The count rides the streamed facets payload; until it resolves (or if it
    // errors) it is undefined — never flash a "create" offer on missing data.
    const decision = decideCreatePrompt({
      query: 'Godzilla',
      isAuthenticated: true,
      queryCount: undefined,
    });
    expect(decision.show).toBe(false);
  });

  it('trims whitespace from the query before returning it', () => {
    const decision = decideCreatePrompt({
      query: '   Ghostbusters   ',
      isAuthenticated: true,
      queryCount: 0,
    });
    expect(decision.query).toBe('Ghostbusters');
  });
});
