import { describe, expect, it, vi } from 'vitest';
import { loadEntityPage } from './entity-page-loader.server';

const MOCK = {
  name: 'Eight Ball',
  slug: 'eight-ball',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  titles: [],
  credits: [],
  sources: [],
};

function event(fetch: ReturnType<typeof vi.fn>, slug = 'eight-ball') {
  return {
    fetch,
    url: new URL(`http://localhost:5173/series/${slug}`),
    request: new Request(`http://localhost:5173/series/${slug}`),
    params: { slug },
  } as unknown as Parameters<typeof loadEntityPage>[0];
}

describe('loadEntityPage', () => {
  it('GETs the page endpoint and wraps the body under profile', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await loadEntityPage(event(fetch), '/api/pages/series/{public_id}', 'Series');

    expect(result).toEqual({ profile: MOCK, q: '' });
    expect((fetch.mock.calls[0]?.[0] as Request).url).toBe(
      'http://localhost:5173/api/pages/series/eight-ball',
    );
  });

  it('forwards the URL q to the endpoint and returns it committed', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const ev = {
      fetch,
      url: new URL('http://localhost:5173/series/eight-ball?q=%20ball%20'),
      request: new Request('http://localhost:5173/series/eight-ball'),
      params: { slug: 'eight-ball' },
    } as unknown as Parameters<typeof loadEntityPage>[0];

    const result = await loadEntityPage(ev, '/api/pages/series/{public_id}', 'Series');

    expect(result.q).toBe('ball');
    expect((fetch.mock.calls[0]?.[0] as Request).url).toBe(
      'http://localhost:5173/api/pages/series/eight-ball?q=ball',
    );
  });

  it('throws a 404 with the label when the body is missing', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      loadEntityPage(event(fetch, 'nope'), '/api/pages/series/{public_id}', 'Series'),
    ).rejects.toMatchObject({ status: 404, body: { message: 'Series not found' } });
  });

  it('throws the upstream status on other failures', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('boom', { status: 503 }));

    await expect(
      loadEntityPage(event(fetch), '/api/pages/series/{public_id}', 'Series'),
    ).rejects.toMatchObject({ status: 503 });
  });
});
