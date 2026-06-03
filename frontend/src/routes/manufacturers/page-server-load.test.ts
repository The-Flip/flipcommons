import { describe, expect, it, vi } from 'vitest';
import { load } from './+page.server';

const CARD = {
  name: 'Williams',
  slug: 'williams',
  model_count: 50,
  thumbnail_url: null,
};

/** Route the mocked fetch by path: cards vs the streamed facet endpoint. */
function routedFetch(cards: Response) {
  return vi.fn((input: Request) => {
    if (new URL(input.url).pathname.startsWith('/api/pages/manufacturers')) {
      return Promise.resolve(
        new Response(JSON.stringify({ filter_options: {}, query_count: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }
    return Promise.resolve(cards);
  });
}

function event(fetch: ReturnType<typeof vi.fn>, search = '') {
  const url = new URL(`http://localhost:5173/manufacturers${search}`);
  return {
    fetch,
    url,
    request: new Request(url),
  } as unknown as Parameters<typeof load>[0];
}

describe('/manufacturers +page.server load', () => {
  it('awaits page 1 cards and returns items/count/query', async () => {
    const fetch = routedFetch(
      new Response(JSON.stringify({ items: [CARD], count: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load(event(fetch, '?q=williams'));
    if (!result) throw new Error('expected load to return page data');

    expect(result.items).toEqual([CARD]);
    expect(result.count).toBe(1);
    expect(result.query.q).toBe('williams');
    // The query-only count is streamed from the facet endpoint, not awaited on the
    // card critical path.
    await expect(result.query_count).resolves.toBe(0);
    // Cards are fetched for page 1.
    const cardCall = fetch.mock.calls.find(
      (c) => new URL((c[0] as Request).url).pathname === '/api/manufacturers/',
    );
    expect(cardCall).toBeDefined();
    expect((cardCall![0] as Request).url).toContain('page=1');
  });

  it('throws instead of degrading to empty when the card fetch fails', async () => {
    const fetch = routedFetch(new Response('boom', { status: 500 }));
    await expect(load(event(fetch, '?q=williams'))).rejects.toMatchObject({ status: 500 });
  });
});
