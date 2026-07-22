import { render } from 'svelte/server';
import { describe, expect, it, vi } from 'vitest';
import Harness from './title-detail.test-harness.svelte';
import { load } from './+layout.server';
import { makeModelDetail } from '$lib/api/detail-fixtures';
import type { TitleDetailSchema } from '$lib/api/schema';

const MOCK_TITLE = {
  name: 'Medieval Madness',
  public_id: 'medieval-madness',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'medieval-madness',
  abbreviations: [],
  description: { text: '', plain: '', html: '', citations: [], attribution: null },
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
} satisfies TitleDetailSchema;

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

    expect(result).toEqual(expect.objectContaining({ profile: MOCK_TITLE }));
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
        data: { profile: MOCK_TITLE, jsonLd: {} },
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
        public_id: 'medieval-madness',
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
        remakes: [],
        title_models: [],
        production_quantity: '',
      },
    };

    const { body } = render(Harness, {
      props: {
        data: { profile: singleModelTitle, jsonLd: {} },
      } as never,
    });

    // Three citation entries, two unique indices — heading should reflect
    // the deduplicated count to match what ReferencesSection renders.
    expect(body).toContain('References (2)');
  });

  // Single-model title lineage renders in the desktop sidebar (see
  // title-layout.test.ts) and, because that sidebar is hidden on mobile, in a
  // mobile-only Related Models accordion here. Its body is lazy, so SSR shows
  // the accordion heading but not the per-relation sections. The old standalone
  // Related Titles / Bootlegs accordions must be gone.
  it('renders a mobile Related Models accordion, not the old lineage accordions', () => {
    const { body } = render(Harness, {
      props: {
        data: {
          profile: {
            ...MOCK_TITLE,
            model_detail: makeModelDetail({
              name: 'Video Pinball',
              public_id: 'video-pinball',
              slug: 'video-pinball',
              relationships: [
                {
                  relationship_type: 'copy',
                  license_status: 'unlicensed',
                  target_machine: { name: 'Jungle Life', public_id: 'jungle-life', year: 1978 },
                  target_label: '',
                },
              ],
              inbound_relationships: [
                {
                  relationship_type: 'copy',
                  license_status: 'unlicensed',
                  source_machine: { name: 'Rugby', public_id: 'rugby-sidam', year: 1979 },
                },
              ],
            }),
            related_titles: [
              {
                relation: 'copy',
                license_status: 'unlicensed',
                other_title: { name: 'Jungle Life', public_id: 'jungle-life' },
                source_model: { name: 'Video Pinball', public_id: 'video-pinball' },
              },
            ],
          },
          jsonLd: {},
        },
      } as never,
    });

    expect(body).toContain('Related Models');
    expect(body).not.toContain('Related Titles');
    expect(body).not.toContain('Bootlegs');
  });

  it('omits the mobile Related Models accordion when the model has no lineage', () => {
    const { body } = render(Harness, {
      props: {
        data: {
          profile: {
            ...MOCK_TITLE,
            model_detail: makeModelDetail({ name: 'Solo', public_id: 'solo', slug: 'solo' }),
          },
          jsonLd: {},
        },
      } as never,
    });

    expect(body).not.toContain('Related Models');
  });

  describe('source data debug panel', () => {
    // A single-model title is the ONLY way to reach the collapsed model's
    // parked source data: /models/{slug} 301s to this page, so a regression
    // here silently hides the panel for those records rather than breaking
    // anything visibly.
    const withDebug = (extra_data: Record<string, unknown>) => ({
      ...MOCK_TITLE,
      model_detail: makeModelDetail({ extra_data }),
    });

    it('renders the collapsed model source data when the flag is on', () => {
      const { body } = render(Harness, {
        props: {
          data: { profile: withDebug({ 'ipdb.notes': 'Parked note.' }), jsonLd: {} },
        } as never,
      });

      expect(body).toContain('Source Debug');
    });

    it('renders nothing when the model has nothing parked', () => {
      const { body } = render(Harness, {
        props: { data: { profile: withDebug({}), jsonLd: {} } } as never,
      });

      expect(body).not.toContain('Source Debug');
    });

    it('omits the panel for a multi-model title, which has no collapsed model', () => {
      const { body } = render(Harness, {
        props: { data: { profile: { ...MOCK_TITLE, model_detail: null }, jsonLd: {} } } as never,
      });

      expect(body).not.toContain('Source Debug');
    });
  });
});
