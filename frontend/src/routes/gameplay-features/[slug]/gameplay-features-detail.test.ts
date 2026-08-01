import { describe, expect, it, vi } from 'vitest';
import type { GameplayFeatureDetailPageSchema } from '$lib/api/schema';
import { load } from './+layout.server';
import { makeGamesList } from '$lib/api/detail-fixtures';

const MOCK_DATA = {
  name: 'Multiball',
  public_id: 'multiball',
  slug: 'multiball',
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  last_modified: '2024-01-01T00:00:00Z',
  aliases: [],
  parents: [],
  children: [],
  uploaded_media: [],
  games: makeGamesList(),
} satisfies GameplayFeatureDetailPageSchema;

describe('gameplay-features detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/gameplay-features/multiball'),
      params: { slug: 'multiball' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({
      profile: MOCK_DATA,
      q: '',
      jsonLd: expect.objectContaining({ '@context': 'https://schema.org' }),
    });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/gameplay-feature/multiball');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/gameplay-features/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });
});
