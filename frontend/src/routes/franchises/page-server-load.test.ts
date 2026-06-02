import { describe, expect, it, vi } from 'vitest';
import { load } from './+page.server';

const ROW = { name: 'Star Wars', slug: 'star-wars', title_count: 4 };

function jsonFetch(body: unknown, status = 200) {
  return vi.fn<(input: Request) => Promise<Response>>(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  );
}

function event(fetch: ReturnType<typeof vi.fn>, search = '') {
  const url = new URL(`http://localhost:5173/franchises${search}`);
  return {
    fetch,
    url,
    request: new Request(url),
  } as unknown as Parameters<typeof load>[0];
}

describe('/franchises +page.server load', () => {
  it('awaits page 1 and returns items/count/q', async () => {
    const fetch = jsonFetch({ items: [ROW], count: 1 });

    const result = await load(event(fetch, '?q=star'));
    if (!result) throw new Error('expected load to return page data');

    expect(result.items).toEqual([ROW]);
    expect(result.count).toBe(1);
    expect(result.q).toBe('star');

    const call = fetch.mock.calls.find(
      (c) => new URL((c[0] as Request).url).pathname === '/api/franchises/',
    );
    expect(call).toBeDefined();
    expect((call![0] as Request).url).toContain('page=1');
    expect((call![0] as Request).url).toContain('q=star');
  });

  it('defaults q to empty when absent', async () => {
    const fetch = jsonFetch({ items: [], count: 0 });
    const result = await load(event(fetch));
    if (!result) throw new Error('expected load to return page data');
    expect(result.q).toBe('');
  });

  it('throws instead of degrading to empty when the fetch fails', async () => {
    // A 500 must surface as an error page, not a silent "0 franchises" success
    // (which would also mislead the create prompt on a query).
    const fetch = jsonFetch('boom', 500);
    await expect(load(event(fetch, '?q=star'))).rejects.toMatchObject({ status: 500 });
  });
});
