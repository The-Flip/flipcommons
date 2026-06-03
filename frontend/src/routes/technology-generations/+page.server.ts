import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import type { PageServerLoad } from './$types';

/**
 * SSR load for /technology-generations. The full grouped hierarchy is **awaited**
 * (no pagination — it's a small, fully-nested taxonomy) so it lands in the server
 * HTML. A backend failure surfaces as an error page rather than a misleading
 * empty success.
 */
export const load: PageServerLoad = async ({ fetch, url, request }) => {
  const client = createServerClient(fetch, url, request);

  const { data, response } = await client.GET('/api/technology-generations/');
  if (!data) {
    throw error(response.status || 500, 'Failed to load technology generations');
  }

  return { items: data };
};
