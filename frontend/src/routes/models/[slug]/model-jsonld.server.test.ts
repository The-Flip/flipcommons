import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { ModelDetailSchema } from '$lib/api/schema';

const ORIGIN = 'http://localhost:5173';

const BASE_MODEL = {
  name: 'Medieval Madness (Williams)',
  public_id: 'medieval-madness-1997',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'medieval-madness-1997',
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
  year: 1997,
  hero_image_url: null,
  corporate_entity: null,
  title: { name: 'Medieval Madness', public_id: 'medieval-madness' },
} satisfies ModelDetailSchema;

function event(profile: ModelDetailSchema, slug = profile.slug) {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(profile), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  return {
    fetch,
    url: new URL(`${ORIGIN}/models/${slug}`),
    request: new Request(`${ORIGIN}/models/${slug}`),
    params: { slug },
  } as unknown as Parameters<typeof load>[0];
}

describe('model +layout.server jsonLd', () => {
  it('emits the Game/ProductModel node with releaseDate', async () => {
    const { jsonLd } = (await load(event(BASE_MODEL))) as { jsonLd: Record<string, unknown> };
    const node = (jsonLd['@graph'] as Record<string, unknown>[])[0];
    expect(node['@type']).toEqual(['Game', 'ProductModel']);
    expect(node['@id']).toBe(`${ORIGIN}/models/medieval-madness-1997`);
    expect(node.releaseDate).toBe('1997');
  });

  // The breadcrumb chain (Home › Titles › Title › Model) is asserted centrally
  // in src/lib/breadcrumbs.server.test.ts, alongside every other entity's.
});
