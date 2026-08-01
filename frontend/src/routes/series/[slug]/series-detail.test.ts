import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';
import { load } from './+layout.server';
import type { SeriesDetailPageSchema } from '$lib/api/schema';
import { emptyPin } from '$lib/api/detail-fixtures';

const MOCK_DATA = {
  name: 'Eight Ball',
  public_id: 'eight-ball',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'eight-ball',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  games: {
    pin: emptyPin(),
    items: [
      {
        entity_type: 'title' as const,
        name: 'Eight Ball Deluxe',
        public_id: 'eight-ball-deluxe',
        year: 1981,
        manufacturer: { name: 'Bally', public_id: 'bally' },
        thumbnail_url: null,
      },
    ],
    count: 1,
  },
  credits: [],
} satisfies SeriesDetailPageSchema;

describe('series detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/series/eight-ball'),
      params: { slug: 'eight-ball' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual(expect.objectContaining({ profile: MOCK_DATA }));
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/series/eight-ball');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/series/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('renders meaningful content into initial HTML', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: MOCK_DATA, q: '', jsonLd: {} },
      },
    });

    expect(body).toContain('Eight Ball Deluxe');
  });
});
