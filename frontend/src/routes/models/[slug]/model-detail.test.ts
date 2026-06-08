import { describe, expect, it, vi } from 'vitest';
import { makeModelDetail } from '$lib/api/detail-fixtures';
import { load } from './+layout.server';

const MOCK_MODEL = makeModelDetail({
  year: 1997,
  manufacturer: { name: 'Williams', public_id: 'williams' },
  corporate_entity: { name: 'Williams Electronics', public_id: 'williams-electronics' },
  credits: [
    {
      person: { name: 'Pat Lawlor', public_id: 'pat-lawlor' },
      role: 'designer',
      role_display: 'Designed',
      role_sort_order: 1,
    },
  ],
});

describe('model detail SSR route', () => {
  it('loads the model from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_MODEL), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/models/medieval-madness'),
      params: { slug: 'medieval-madness' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual(expect.objectContaining({ profile: MOCK_MODEL }));
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/model/medieval-madness');
  });

  it('throws 404 when the model is not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/models/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  // Credits and other content are rendered by the layout's accordion
  // sections, not by +page.svelte (which is now an empty shell).
});
