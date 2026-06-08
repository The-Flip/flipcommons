import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { ModelDetailSchema } from '$lib/api/schema';
import { makeModelDetail } from '$lib/api/detail-fixtures';

const ORIGIN = 'http://localhost:5173';

const BASE_MODEL = makeModelDetail({
  name: 'Medieval Madness (Williams)',
  public_id: 'medieval-madness-1997',
  slug: 'medieval-madness-1997',
  year: 1997,
});

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
