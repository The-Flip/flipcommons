import { describe, expect, it, vi } from 'vitest';
import { load } from './+layout.server';
import type { LocationDetailSchema } from '$lib/api/schema';

const ORIGIN = 'http://localhost:5173';

const CHICAGO = {
  name: 'Chicago',
  public_id: 'usa/il/chicago',
  last_modified: '2026-01-01T00:00:00Z',
  slug: 'chicago',
  location_type: 'city',
  expected_child_type: null,
  short_name: null,
  code: null,
  divisions: null,
  aliases: [],
  manufacturer_count: 0,
  description: { text: '', html: '', plain: '', citations: [], attribution: null },
  ancestors: [
    { name: 'United States', public_id: 'usa' },
    { name: 'Illinois', public_id: 'usa/il' },
  ],
  children: [],
  manufacturers: [],
} satisfies LocationDetailSchema;

function event(profile: unknown, path: string) {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(profile), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  return {
    fetch,
    url: new URL(`${ORIGIN}/locations/${path}`),
    request: new Request(`${ORIGIN}/locations/${path}`),
    params: { path },
  } as unknown as Parameters<typeof load>[0];
}

describe('location +layout.server jsonLd', () => {
  it('emits a typed Place node with a Home › ancestors breadcrumb', async () => {
    const data = (await load(event(CHICAGO, 'usa/il/chicago'))) as {
      jsonLd?: Record<string, unknown>;
    };
    const jsonLd = data.jsonLd;
    if (!jsonLd) throw new Error('expected jsonLd for a concrete location');
    const graph = jsonLd['@graph'] as Record<string, unknown>[];

    const node = graph[0];
    expect(node['@type']).toBe('City');
    expect(node['@id']).toBe(`${ORIGIN}/locations/usa/il/chicago`);

    const crumb = graph.find((n) => n['@type'] === 'BreadcrumbList');
    const items = crumb?.itemListElement as Record<string, unknown>[];
    expect(items.map((i) => i.name)).toEqual(['Home', 'United States', 'Illinois', 'Chicago']);
    expect(items[1].item).toBe(`${ORIGIN}/locations/usa`);
    expect(items[2].item).toBe(`${ORIGIN}/locations/usa/il`);
  });

  it('emits no JSON-LD for the global root (path === "")', async () => {
    const root = { name: '', public_id: '', location_type: null, manufacturers: [] };
    const data = (await load(event(root, ''))) as { jsonLd?: Record<string, unknown> };
    expect(data.jsonLd).toBeUndefined();
  });
});
