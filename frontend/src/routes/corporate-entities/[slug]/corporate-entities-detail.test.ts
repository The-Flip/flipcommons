import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';
import { load } from './+layout.server';

const MOCK_DATA = {
  name: 'Williams Electronics',
  public_id: 'williams-electronics',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'williams-electronics',
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  manufacturer: { name: 'Williams', public_id: 'williams' },
  year_start: 1985,
  year_end: 1999,
  aliases: [],
  titles: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      manufacturer_name: 'Williams',
      thumbnail_url: null,
    },
  ],
  locations: [],
  sources: [],
};

describe('corporate-entities detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/corporate-entities/williams-electronics'),
      params: { slug: 'williams-electronics' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({ profile: MOCK_DATA });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe(
      'http://localhost:5173/api/pages/corporate-entity/williams-electronics',
    );
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/corporate-entities/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('renders meaningful content into initial HTML', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: MOCK_DATA },
      },
    });

    expect(body).toContain('Medieval Madness');
  });

  it('renders the empty-state message when there are no titles', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: { ...MOCK_DATA, titles: [] } },
      },
    });

    expect(body).toContain('No titles listed for this corporate entity.');
  });
});
