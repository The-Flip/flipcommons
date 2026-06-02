import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import type { PageServerLoad } from './$types';

/**
 * SSR load for /systems. Two awaited calls: the paginated page-1 cards
 * (`/api/systems/`, optionally filtered by `manufacturer`), and the full system
 * list (`/api/systems/all/`) from which we derive the manufacturer dropdown
 * options — the page's old client-side derivation moved server-side. systems is
 * a small set, so the extra full-list await is cheap. A backend failure on
 * either surfaces as an error page rather than a misleading empty success.
 */
export const load: PageServerLoad = async ({ fetch, url, request }) => {
  const client = createServerClient(fetch, url, request);
  const q = url.searchParams.get('q') ?? '';
  const manufacturer = url.searchParams.get('manufacturer') ?? '';

  const [page, all] = await Promise.all([
    client.GET('/api/systems/', {
      params: { query: { q, manufacturer: manufacturer || undefined, page: 1 } },
    }),
    client.GET('/api/systems/all/'),
  ]);

  if (!page.data) {
    throw error(page.response.status || 500, 'Failed to load systems');
  }
  if (!all.data) {
    throw error(all.response.status || 500, 'Failed to load systems');
  }

  // Distinct system-bearing manufacturers, alphabetical. `public_id` is the
  // manufacturer's slug (its `public_id_field`), which is exactly the value the
  // `?manufacturer=` filter param expects — no extra mapping.
  const seen = new Map<string, string>();
  for (const s of all.data) {
    if (!seen.has(s.manufacturer.public_id)) {
      seen.set(s.manufacturer.public_id, s.manufacturer.name);
    }
  }
  const manufacturerOptions = [...seen.entries()]
    .map(([value, name]) => ({ value, name }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return {
    items: page.data.items,
    count: page.data.count,
    q,
    manufacturer,
    manufacturerOptions,
  };
};
