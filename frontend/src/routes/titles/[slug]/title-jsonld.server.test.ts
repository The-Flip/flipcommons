import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { TitleDetailSchema, ModelDetailSchema } from '$lib/api/schema';

const ORIGIN = 'http://localhost:5173';

const BASE_TITLE = {
  name: 'Medieval Madness',
  public_id: 'medieval-madness',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'medieval-madness',
  abbreviations: [],
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  needs_review: false,
  needs_review_notes: '',
  review_links: [],
  hero_image_url: null,
  franchise: null,
  series: null,
  credits: [],
  agreed_specs: { themes: [], gameplay_features: [], reward_types: [], tags: [] },
  related_titles: [],
  media: [],
  opdb_id: null,
  fandom_page_id: null,
  model_detail: null,
  machines: [],
} satisfies TitleDetailSchema;

const MODEL_DETAIL = {
  name: 'Doctor Who',
  public_id: 'doctor-who-1992',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'doctor-who-1992',
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  abbreviations: [],
  extra_data: {},
  credits: [],
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
  year: 1992,
  title: { name: 'Doctor Who', public_id: 'doctor-who' },
} satisfies ModelDetailSchema;

function machine(name: string, public_id: string) {
  return {
    name,
    public_id,
    year: 1997,
    manufacturer: null,
    technology_generation_name: null,
    thumbnail_url: null,
    variants: [],
  };
}

function event(profile: TitleDetailSchema, slug = profile.slug) {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(profile), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  return {
    fetch,
    url: new URL(`${ORIGIN}/titles/${slug}`),
    request: new Request(`${ORIGIN}/titles/${slug}`),
    params: { slug },
  } as unknown as Parameters<typeof load>[0];
}

async function graphOf(profile: TitleDetailSchema) {
  // `load` is typed `void | OutputData`; in the 200 path it always resolves to
  // the object, so narrow it locally.
  const { jsonLd } = (await load(event(profile))) as { jsonLd: Record<string, unknown> };
  return jsonLd['@graph'] as Record<string, unknown>[];
}

describe('title +layout.server jsonLd', () => {
  it('single-Model title emits both Title and Model nodes cross-linked by @id', async () => {
    const graph = await graphOf({
      ...BASE_TITLE,
      name: 'Doctor Who',
      public_id: 'doctor-who',
      slug: 'doctor-who',
      machines: [machine('Doctor Who', 'doctor-who-1992')],
      model_detail: MODEL_DETAIL,
    });

    const titleNode = graph[0];
    expect(titleNode['@type']).toBe('Game');
    expect(titleNode['@id']).toBe(`${ORIGIN}/titles/doctor-who`);
    // workExample is a single object pointing at the Model's @id.
    expect(titleNode.workExample).toEqual({ '@id': `${ORIGIN}/models/doctor-who-1992` });

    const modelNode = graph[1];
    expect(modelNode['@type']).toEqual(['Game', 'ProductModel']);
    expect(modelNode['@id']).toBe(`${ORIGIN}/models/doctor-who-1992`);
    expect(modelNode.releaseDate).toBe('1992');

    // The breadcrumb is the last node.
    expect(graph[graph.length - 1]['@type']).toBe('BreadcrumbList');
  });

  it('multi-Model title emits one Title node with a workExample array, no Model node', async () => {
    const graph = await graphOf({
      ...BASE_TITLE,
      machines: [machine('MM A', 'mm-a'), machine('MM B', 'mm-b')],
      model_detail: null,
    });

    const titleNode = graph[0];
    expect(titleNode.workExample).toEqual([
      { '@id': `${ORIGIN}/models/mm-a` },
      { '@id': `${ORIGIN}/models/mm-b` },
    ]);

    // Only the Title node + breadcrumb — no embedded Model node.
    expect(graph).toHaveLength(2);
    expect(graph[1]['@type']).toBe('BreadcrumbList');
  });

  it('omits workExample when the title has no machines', async () => {
    const graph = await graphOf({ ...BASE_TITLE, machines: [], model_detail: null });
    expect(graph[0]).not.toHaveProperty('workExample');
  });
});
