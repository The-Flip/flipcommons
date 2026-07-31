import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { TaxonomyPageSchema } from '$lib/api/schema';

const MOCK_DATA = {
  name: 'Dot Matrix',
  public_id: 'dot-matrix',
  slug: 'dot-matrix',
  display_order: 0,
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  last_modified: '2024-01-01T00:00:00Z',
  aliases: [],
  games: { items: [], count: 0 },
} satisfies TaxonomyPageSchema;

describe('display-types detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/display-types/dot-matrix'),
      params: { slug: 'dot-matrix' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({
      profile: MOCK_DATA,
      q: '',
      jsonLd: expect.objectContaining({ '@context': 'https://schema.org' }),
    });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/display-type/dot-matrix');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/display-types/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });
});
