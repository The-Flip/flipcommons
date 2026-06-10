import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { CorporateEntityDetailSchema } from '$lib/api/schema';
import { MOCK_CORPORATE_ENTITY } from './corporate-entity.fixtures';

const ORIGIN = 'http://localhost:5173';

// Bally-specific founding/dissolution years and brand ref drive this test's
// jsonLd assertions, so override them on the shared fixture.
const CE = {
  ...MOCK_CORPORATE_ENTITY,
  name: 'Bally',
  public_id: 'bally',
  slug: 'bally',
  manufacturer: { name: 'Bally', public_id: 'bally-mfr' },
  year_start: 1931,
  year_end: 1998,
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
