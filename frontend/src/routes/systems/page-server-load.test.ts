import { describe, expect, it, vi } from 'vitest';
import { load } from './+page.server';

const WPC = {
  name: 'WPC-95',
  slug: 'wpc-95',
  manufacturer: { public_id: 'williams', name: 'Williams' },
  model_count: 30,
};
const SPIKE = {
  name: 'SPIKE',
  slug: 'spike',
  manufacturer: { public_id: 'stern', name: 'Stern' },
  model_count: 42,
};
const WHITESTAR = {
  name: 'Whitestar',
  slug: 'whitestar',
  manufacturer: { public_id: 'stern', name: 'Stern' },
  model_count: 12,
};

/** Routes by pathname: `/api/systems/all/` → the full list, else the paginated page. */
function routedFetch(page: unknown, all: unknown, status = 200) {
  return vi.fn<(input: Request) => Promise<Response>>((input) => {
    const path = new URL(input.url).pathname;
    const body = path === '/api/systems/all/' ? all : page;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });
}

function event(fetch: ReturnType<typeof vi.fn>, search = '') {
  const url = new URL(`http://localhost:5173/systems${search}`);
  return { fetch, url, request: new Request(url) } as unknown as Parameters<typeof load>[0];
}

describe('/systems +page.server load', () => {
  it('awaits page 1 and derives distinct, alphabetical manufacturer options from /all/', async () => {
    const fetch = routedFetch({ items: [WPC], count: 1 }, [WPC, SPIKE, WHITESTAR]);

    const result = await load(event(fetch));
    if (!result) throw new Error('expected load to return page data');

    expect(result.items).toEqual([WPC]);
    expect(result.count).toBe(1);
    // Stern appears once despite owning two systems; alphabetical; value is the slug.
    expect(result.manufacturerOptions).toEqual([
      { value: 'stern', name: 'Stern' },
      { value: 'williams', name: 'Williams' },
    ]);
  });

  it('forwards the manufacturer filter to the paginated call and echoes it back', async () => {
    const fetch = routedFetch({ items: [WPC], count: 1 }, [WPC, SPIKE]);

    const result = await load(event(fetch, '?manufacturer=williams&q=wpc'));
    if (!result) throw new Error('expected load to return page data');
    expect(result.manufacturer).toBe('williams');
    expect(result.q).toBe('wpc');

    const call = fetch.mock.calls.find(
      (c) => new URL((c[0] as Request).url).pathname === '/api/systems/',
    );
    expect(call).toBeDefined();
    expect((call![0] as Request).url).toContain('manufacturer=williams');
    expect((call![0] as Request).url).toContain('q=wpc');
  });

  it('throws instead of degrading to empty when a fetch fails', async () => {
    const fetch = routedFetch('boom', 'boom', 500);
    await expect(load(event(fetch))).rejects.toMatchObject({ status: 500 });
  });
});
