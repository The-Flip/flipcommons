import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { CorporateEntityDetailSchema } from '$lib/api/schema';

const ORIGIN = 'http://localhost:5173';

const CE = {
  name: 'Bally',
  public_id: 'bally',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'bally',
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  manufacturer: { name: 'Bally', public_id: 'bally-mfr' },
  year_start: 1931,
  year_end: 1998,
  aliases: [],
  locations: [],
  titles: [],
} satisfies CorporateEntityDetailSchema;

function event(profile: CorporateEntityDetailSchema, slug = profile.slug) {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(profile), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  return {
    fetch,
    url: new URL(`${ORIGIN}/corporate-entities/${slug}`),
    request: new Request(`${ORIGIN}/corporate-entities/${slug}`),
    params: { slug },
  } as unknown as Parameters<typeof load>[0];
}

describe('corporate-entity +layout.server jsonLd', () => {
  it('emits an Organization with founding/dissolution years and a brand ref', async () => {
    const { jsonLd } = (await load(event(CE))) as { jsonLd: Record<string, unknown> };
    const node = (jsonLd['@graph'] as Record<string, unknown>[])[0];
    expect(node['@type']).toBe('Organization');
    expect(node['@id']).toBe(`${ORIGIN}/corporate-entities/bally`);
    expect(node.foundingDate).toBe('1931');
    expect(node.dissolutionDate).toBe('1998');
    expect(node.brand).toEqual({ '@id': `${ORIGIN}/manufacturers/bally-mfr` });
  });
});
