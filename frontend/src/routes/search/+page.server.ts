import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { MIN_SEARCH_QUERY_LENGTH } from '$lib/constants';
import type { PageServerLoad } from './$types';

/**
 * SSR load for /search. With a long-enough `q` the one search endpoint is
 * **awaited** so the result cards land in the server HTML (fast first paint, no
 * client blob loads). Below the threshold we return `results: null` and skip the
 * call — the page renders the "type at least N characters" hint. A backend
 * failure surfaces as an error page rather than a misleading empty result set.
 */
export const load: PageServerLoad = async ({ fetch, url, request }) => {
  const client = createServerClient(fetch, url, request);
  const q = (url.searchParams.get('q') ?? '').trim();

  if (q.length < MIN_SEARCH_QUERY_LENGTH) {
    return { q, results: null };
  }

  const { data, response } = await client.GET('/api/pages/search', {
    params: { query: { q } },
  });
  if (!data) {
    throw error(response.status || 500, 'Search failed');
  }

  return { q, results: data };
};
