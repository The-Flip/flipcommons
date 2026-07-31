import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';
import { load } from './+layout.server';
import type { FranchiseDetailPageSchema } from '$lib/api/schema';

const MOCK_DATA = {
  name: 'Star Trek',
  public_id: 'star-trek',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'star-trek',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  games: {
    items: [
      {
        entity_type: 'title' as const,
        name: 'Star Trek TNG',
        public_id: 'star-trek-tng',
        year: 1993,
        manufacturer: { name: 'Williams', public_id: 'williams' },
        thumbnail_url: null,
      },
    ],
    count: 1,
  },
} satisfies FranchiseDetailPageSchema;

describe('franchises detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/franchises/star-trek'),
      params: { slug: 'star-trek' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual(expect.objectContaining({ profile: MOCK_DATA }));
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/franchise/star-trek');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/franchises/nonexistent'),
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

    expect(body).toContain('Games (1)');
  });
});
