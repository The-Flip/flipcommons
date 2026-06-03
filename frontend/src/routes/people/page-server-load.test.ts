import { describe, expect, it, vi } from 'vitest';
import { load } from './+page.server';

const CARD = { name: 'Pat Lawlor', slug: 'pat-lawlor', thumbnail_url: null, credit_count: 12 };

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
  const url = new URL(`http://localhost:5173/people${search}`);
  return {
    fetch,
    url,
    request: new Request(url),
  } as unknown as Parameters<typeof load>[0];
}

describe('/people +page.server load', () => {
  it('awaits page 1 of the paginated endpoint and returns items/count/q', async () => {
    const fetch = jsonFetch({ items: [CARD], count: 1 });

    const result = await load(event(fetch, '?q=lawlor'));
    if (!result) throw new Error('expected load to return page data');

    expect(result.items).toEqual([CARD]);
    expect(result.count).toBe(1);
    expect(result.q).toBe('lawlor');

    // The page now reads the paginated `/api/people/`, not the old `/all/`.
    const call = fetch.mock.calls.find(
      (c) => new URL((c[0] as Request).url).pathname === '/api/people/',
    );
    expect(call).toBeDefined();
    expect((call![0] as Request).url).toContain('page=1');
    expect((call![0] as Request).url).toContain('q=lawlor');
  });

  it('defaults q to empty when absent', async () => {
    const fetch = jsonFetch({ items: [], count: 0 });
    const result = await load(event(fetch));
    if (!result) throw new Error('expected load to return page data');
    expect(result.q).toBe('');
  });

  it('throws instead of degrading to empty when the fetch fails', async () => {
    const fetch = jsonFetch('boom', 500);
    await expect(load(event(fetch, '?q=lawlor'))).rejects.toMatchObject({ status: 500 });
  });
});
