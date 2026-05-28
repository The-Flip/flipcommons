import { describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import Page from './people-detail.test-harness.svelte';
import { load } from './+layout.server';

const MOCK_DATA = {
  name: 'Pat Lawlor',
  slug: 'pat-lawlor',
  description: {
    text: 'Pinball designer.',
    plain: 'Pinball designer.',
    html: '<p>Pinball designer.</p>',
    citations: [],
    attribution: null,
  },
  birth_year: 1951,
  birth_month: null,
  birth_day: null,
  death_year: null,
  death_month: null,
  death_day: null,
  birth_place: null,
  nationality: 'American',
  photo_url: null,
  titles: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      manufacturer_name: 'Williams',
      thumbnail_url: null,
      roles: ['Design'],
    },
  ],
  uploaded_media: [],
  sources: [],
};

describe('people detail SSR route', () => {
  it('loads from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_DATA), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/people/pat-lawlor'),
      params: { slug: 'pat-lawlor' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({ person: MOCK_DATA });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/person/pat-lawlor');
  });

  it('throws 404 when not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/people/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('renders meaningful content into initial HTML', () => {
    const { body } = render(Page, {
      props: {
        data: { person: MOCK_DATA },
      },
    });

    expect(body).toContain('Bio');
    expect(body).toContain('Details');
    expect(body).toContain('Credits (1)');
  });
});
