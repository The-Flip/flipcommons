import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';
import { load } from './+layout.server';

const MOCK_DATA = {
  name: 'WPC-95',
  public_id: 'wpc-95',
  slug: 'wpc-95',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  manufacturer: { name: 'Williams', public_id: 'williams' },
  technology_subgeneration: { name: 'Integrated', public_id: 'integrated' },
  titles: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      manufacturer_name: 'Williams',
      thumbnail_url: null,
    },
  ],
  sibling_systems: [],
  sources: [],
};

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
        data: { profile: MOCK_DATA, jsonLd: {} },
      },
    });

    expect(body).toContain('Medieval Madness');
    expect(body).toContain('Titles using WPC-95 (1)');
  });
});
