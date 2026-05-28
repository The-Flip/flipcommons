import { render } from 'svelte/server';
import { describe, expect, it, vi } from 'vitest';
import Harness from './title-detail.test-harness.svelte';
import { load } from './+layout.server';

const MOCK_TITLE = {
  name: 'Medieval Madness',
  slug: 'medieval-madness',
  abbreviations: [],
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
  needs_review: false,
  needs_review_notes: '',
  review_links: [],
  hero_image_url: null,
  franchise: null,
  machines: [
    {
      name: 'Medieval Madness',
      public_id: 'medieval-madness',
      year: 1997,
      manufacturer: { name: 'Williams', public_id: 'williams' },
      technology_generation_name: 'Solid State',
      thumbnail_url: null,
      variants: [],
    },
  ],
  series: null,
  credits: [],
  agreed_specs: { themes: [], gameplay_features: [], reward_types: [], tags: [] },
  related_titles: [],
  media: [],
  opdb_id: null,
  fandom_page_id: null,
  model_detail: null,
  sources: [],
};

describe('title detail SSR route', () => {
  it('loads the title from the page endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(MOCK_TITLE), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await load({
      fetch,
      url: new URL('http://localhost:5173/titles/medieval-madness'),
      params: { slug: 'medieval-madness' },
    } as unknown as Parameters<typeof load>[0]);

    expect(result).toEqual({ title: MOCK_TITLE });
    const request = fetch.mock.calls[0]?.[0];
    expect(request).toBeInstanceOf(Request);
    expect(request.url).toBe('http://localhost:5173/api/pages/title/medieval-madness');
  });

  it('throws 404 when the title is not found', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('Not found', { status: 404 }));

    await expect(
      load({
        fetch,
        url: new URL('http://localhost:5173/titles/nonexistent'),
        params: { slug: 'nonexistent' },
      } as unknown as Parameters<typeof load>[0]),
    ).rejects.toMatchObject({ status: 404 });
  });

  it('renders meaningful title content into initial HTML', () => {
    const { body } = render(Harness, {
      props: {
        data: { title: MOCK_TITLE },
      },
    });

    // The page renders a tab label showing the machine count, proving
    // backend data reached the server-rendered HTML.
    expect(body).toContain('Models (1)');
  });

  it('deduplicates citation count in References heading for single-model titles', () => {
    const makeCite = (id: number, index: number) => ({
      id,
      index,
      source_name: 'Source',
      source_type: 'book',
      author: 'Author',
      year: 2000,
      locator: '',
      links: [],
    });
    const singleModelTitle = {
      ...MOCK_TITLE,
      model_detail: {
        name: 'Medieval Madness',
        slug: 'medieval-madness',
        description: {
          text: 'foo [1] bar [2] baz [1]',
          plain: 'foo bar baz',
          html: '<p>foo bar baz</p>',
          citations: [makeCite(10, 1), makeCite(20, 2), makeCite(30, 1)],
          attribution: null,
        },
        abbreviations: [],
        extra_data: {},
        credits: [],
        sources: [],
        uploaded_media: [],
        variant_features: [],
        variants: [],
        themes: [],
        gameplay_features: [],
        tags: [],
        reward_types: [],
        variant_siblings: [],
        conversions: [],
        remakes: [],
        title_models: [],
        production_quantity: '',
      },
    };

    const { body } = render(Harness, {
      props: {
        data: { title: singleModelTitle },
      } as never,
    });

    // Three citation entries, two unique indices — heading should reflect
    // the deduplicated count to match what ReferencesSection renders.
    expect(body).toContain('References (2)');
  });
});
