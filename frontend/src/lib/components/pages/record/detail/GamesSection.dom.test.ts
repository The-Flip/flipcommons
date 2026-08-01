/**
 * DOM tests for GamesSection's pagination: pages 2+ must be fetched with the
 * embed's own `pin` — nulls and empty lists stripped, values carried verbatim.
 * The sparse preset is the case that motivates this: the widened
 * `['pinball', 'unclassified']` pair must reach page 2's query, or infinite
 * scroll continues a different result set than the embedded page 1.
 */
import { render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { emptyPin, makeGamesList } from '$lib/api/detail-fixtures';

const { mockGET } = vi.hoisted(() => ({ mockGET: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { GET: mockGET } }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', () => ({
  page: { url: new URL('http://localhost/game-formats/pinball') },
}));

import GamesSection from './GamesSection.svelte';

type ObserverEntry = { isIntersecting: boolean };
const observers: { callback: (entries: ObserverEntry[]) => void }[] = [];

beforeEach(() => {
  observers.length = 0;
  mockGET.mockResolvedValue({ data: makeGamesList({ count: 60 }) });
  class MockIntersectionObserver {
    callback: (entries: ObserverEntry[]) => void;
    observe = vi.fn();
    disconnect = vi.fn();

    constructor(callback: (entries: ObserverEntry[]) => void) {
      this.callback = callback;
      observers.push(this);
    }
  }
  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
  mockGET.mockReset();
});

const CARD = {
  entity_type: 'title' as const,
  name: 'Whirlwind',
  public_id: 'whirlwind',
  year: 1990,
  manufacturer: { name: 'Williams', public_id: 'williams' },
  thumbnail_url: null,
  roles: null,
};

describe('GamesSection', () => {
  it('fetches pages 2+ with the payload pin, unset dimensions stripped', async () => {
    render(GamesSection, {
      props: {
        games: makeGamesList({
          items: [CARD],
          count: 60,
          pin: { ...emptyPin(), game_format: ['pinball', 'unclassified'] },
        }),
        q: '',
      },
    });

    observers.forEach((o) => o.callback([{ isIntersecting: true }]));

    await waitFor(() => expect(mockGET).toHaveBeenCalledTimes(1));
    expect(mockGET).toHaveBeenCalledWith('/api/games/', {
      params: { query: { game_format: ['pinball', 'unclassified'], page: 2 } },
    });
  });

  it('composes the active search term with the pin', async () => {
    render(GamesSection, {
      props: {
        games: makeGamesList({
          items: [CARD],
          count: 60,
          pin: { ...emptyPin(), manufacturer: 'williams' },
        }),
        q: 'whirl',
      },
    });

    observers.forEach((o) => o.callback([{ isIntersecting: true }]));

    await waitFor(() => expect(mockGET).toHaveBeenCalledTimes(1));
    expect(mockGET).toHaveBeenCalledWith('/api/games/', {
      params: { query: { manufacturer: 'williams', q: 'whirl', page: 2 } },
    });
  });
});
