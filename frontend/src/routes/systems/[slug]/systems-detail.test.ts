import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';
import { load } from './+layout.server';
import type { SystemDetailPageSchema } from '$lib/api/schema';

const MOCK_DATA = {
  name: 'WPC-95',
  public_id: 'wpc-95',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'wpc-95',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  manufacturer: { name: 'Williams', public_id: 'williams' },
  technology_subgeneration: { name: 'Integrated', public_id: 'integrated' },
  games: {
    items: [
      {
        entity_type: 'title' as const,
        name: 'Medieval Madness',
        public_id: 'medieval-madness',
        year: 1997,
        manufacturer: { name: 'Williams', public_id: 'williams' },
        thumbnail_url: null,
      },
    ],
    count: 1,
  },
  sibling_systems: [],
} satisfies SystemDetailPageSchema;

describe('systems detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/systems/wpc-95'),
      params: { slug: 'wpc-95' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({
      profile: MOCK_DATA,
      q: '',
      jsonLd: expect.objectContaining({ '@context': 'https://schema.org' }),
    });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/system/wpc-95');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/systems/nonexistent'),
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

    expect(body).toContain('Medieval Madness');
    expect(body).toContain('Games (1)');
  });
});
