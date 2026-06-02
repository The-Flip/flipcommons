import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import type { PageServerLoad } from './$types';

/**
 * SSR load for /people. Page 1 is **awaited** so the cards land in the server
 * HTML (crawlable, fast first paint); `q` comes from the URL so a `?q=` link
 * renders its filtered page server-side. A backend failure surfaces as an error
 * page rather than a misleading empty "0 people" success.
 */
export const load: PageServerLoad = async ({ fetch, url, request }) => {
  const client = createServerClient(fetch, url, request);
  const q = url.searchParams.get('q') ?? '';

  const { data, response } = await client.GET('/api/people/', {
    params: { query: { q, page: 1 } },
  });
  if (!data) {
    throw error(response.status || 500, 'Failed to load people');
  }

  return { items: data.items, count: data.count, q };
};
