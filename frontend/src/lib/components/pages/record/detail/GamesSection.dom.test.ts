/**
 * DOM tests for GamesSection's pagination and search box. Pagination: pages 2+
 * must be fetched with the embed's own `pin` — nulls and empty lists stripped,
 * values carried verbatim. The sparse preset is the case that motivates this:
 * the widened `['pinball', 'unclassified']` pair must reach page 2's query, or
 * infinite scroll continues a different result set than the embedded page 1.
 * Search: the box holds a draft that a landing navigation must not rewind.
 */
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { emptyPin, makeGamesList } from '$lib/api/detail-fixtures';

const { mockGET, goto } = vi.hoisted(() => ({ mockGET: vi.fn(), goto: vi.fn() }));
vi.mock('$lib/api/client', () => ({ default: { GET: mockGET } }));
vi.mock('$app/navigation', () => ({ goto }));
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
  goto.mockReset();
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

  describe('search box', () => {
    const props = (q: string) => ({ games: makeGamesList({ items: [CARD], count: 60 }), q });

    it('keeps a draft typed ahead of a landing navigation', async () => {
      const user = userEvent.setup();
      const { rerender } = render(GamesSection, { props: props('') });
      const box = screen.getByRole('searchbox');

      // Type, pause: the debounce commits `?q=god` and the navigation starts.
      await user.type(box, 'god');
      await waitFor(() => expect(goto).toHaveBeenCalledTimes(1));
      expect(goto.mock.calls[0][0]).toBe('/game-formats/pinball?q=god');

      // The user types on while that navigation is still in flight, then it
      // lands and the server load reseeds the committed `q`.
      await user.type(box, 'zi');
      await rerender(props('god'));

      expect(box).toHaveValue('godzi');
    });

    it('adopts a committed q that changes with nothing pending', async () => {
      const { rerender } = render(GamesSection, { props: props('god') });
      expect(screen.getByRole('searchbox')).toHaveValue('god');

      // Back/forward: the committed value changes from outside the box, and
      // the user has no draft in flight — the box follows the URL.
      await rerender(props('gorgar'));

      expect(screen.getByRole('searchbox')).toHaveValue('gorgar');
    });
  });
});
