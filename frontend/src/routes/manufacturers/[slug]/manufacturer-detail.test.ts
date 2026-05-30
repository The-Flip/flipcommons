import { render } from 'svelte/server';
import { describe, expect, it, vi } from 'vitest';
import Page from './manufacturer-detail.test-harness.svelte';
import { load } from './+layout.server';

const MOCK_MANUFACTURER = {
  name: 'Williams',
  public_id: 'williams',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'williams',
  description: {
    text: 'Historic manufacturer [1].',
    plain: 'Historic manufacturer.',
    html: '<p>Historic manufacturer.</p>',
    citations: [
      {
        id: 10,
        index: 1,
        source_name: 'Pinball Sourcebook',
        source_type: 'book',
        author: 'Jane Example',
        year: 1999,
        locator: 'p. 42',
        links: [],
      },
      {
        id: 11,
        index: 1,
        source_name: 'Pinball Sourcebook',
        source_type: 'book',
        author: 'Jane Example',
        year: 1999,
        locator: 'p. 42',
        links: [],
      },
    ],
    attribution: null,
  },
  year_start: 1985,
  year_end: 1999,
  country: null,
  headquarters: null,
  logo_url: null,
  website: 'https://williams.example',
  entities: [
    {
      name: 'Williams Electronics',
      public_id: 'williams-electronics',
      year_start: 1985,
      year_end: 1999,
      locations: [],
    },
  ],
  titles: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      thumbnail_url: null,
    },
  ],
  systems: [{ name: 'WPC-95', public_id: 'wpc-95' }],
  persons: [{ name: 'Pat Lawlor', public_id: 'pat-lawlor', roles: ['Designer'] }],
  uploaded_media: [
    {
      asset_uuid: 'asset-1',
      category: 'cabinet',
      is_primary: true,
      renditions: {
        thumb: 'https://example.com/thumb.jpg',
        display: 'https://example.com/display.jpg',
      },
    },
  ],
  sources: [],
};

describe('manufacturer detail SSR route', () => {
  it('loads the manufacturer from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_MANUFACTURER), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/manufacturers/williams'),
      params: { slug: 'williams' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({
      profile: MOCK_MANUFACTURER,
      jsonLd: expect.objectContaining({ '@context': 'https://schema.org' }),
    });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/manufacturer/williams');
  });

  it('throws 404 when the manufacturer is not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/manufacturers/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('renders meaningful manufacturer content into initial HTML', () => {
    const { body } = render(Page, {
      props: {
        data: { profile: MOCK_MANUFACTURER, jsonLd: {} },
      },
    });

    expect(body).toContain('Overview');
    expect(body).toContain('Companies');
    expect(body).toContain('Titles (1)');
    expect(body).toContain('Systems (1)');
    expect(body).toContain('People (1)');
    expect(body).toContain('Media (1)');
    expect(body).toContain('References (1)');
    expect(body).toContain('Historic manufacturer.');
    expect(body).toContain('>edit<');
  });
});
