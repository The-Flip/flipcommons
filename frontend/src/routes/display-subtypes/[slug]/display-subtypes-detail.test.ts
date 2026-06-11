import { describe, expect, it, vi } from 'vitest';
import type { DisplaySubtypeDetailSchema } from '$lib/api/schema';
import { load } from './+layout.server';

const MOCK_DATA = {
  name: '128x32',
  public_id: '128x32',
  slug: '128x32',
  display_order: 0,
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  aliases: [],
  last_modified: '2024-01-01T00:00:00Z',
  display_type: { name: 'Dot Matrix', public_id: 'dot-matrix' },
} satisfies DisplaySubtypeDetailSchema;

describe('display-subtypes detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/display-subtypes/128x32'),
      params: { slug: '128x32' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({
      profile: MOCK_DATA,
      jsonLd: expect.objectContaining({ '@context': 'https://schema.org' }),
    });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/display-subtype/128x32');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/display-subtypes/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });
});
