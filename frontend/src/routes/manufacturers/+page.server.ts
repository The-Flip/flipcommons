import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { queryFromUrl } from './manufacturers-query';
import type { PageServerLoad } from './$types';

/**
 * SSR load for /manufacturers. The cards are **awaited** so page 1 lands in the
 * server HTML (crawlable). The facet option lists are returned as an **unawaited
 * promise** — SvelteKit streams them down the same chunked response after the cards,
 * so the count badges don't block the grid. The page renders the facet promise with
 * `{#await}`. Mirrors /titles.
 */
export const load: PageServerLoad = async ({ fetch, url, request }) => {
  const client = createServerClient(fetch, url, request);
  const query = queryFromUrl(url);

  const cards = await client.GET('/api/manufacturers/', {
    params: { query: { ...query, page: 1 } },
  });
  // Cards are the critical path: a backend failure must surface as an error page,
  // not degrade to an empty "0 manufacturers" success (which would also mislead the
  // create prompt on a query).
  if (!cards.data) {
    throw error(cards.response.status || 500, 'Failed to load manufacturers');
  }

  const facets = client.GET('/api/pages/manufacturers', { params: { query } });

  return {
    items: cards.data.items,
    count: cards.data.count,
    // The query that produced page 1 — the client grid reuses it for load-more.
    query,
    // Unawaited → streamed after the cards. Resolves to undefined (never rejects) on
    // a facet-endpoint error; the sidebar renders disabled until it lands and shows an
    // inline retry on undefined (see `streamed` + the page's facet state).
    filter_options: facets.then((r) => r.data?.filter_options).catch(() => undefined),
    // Query-only manufacturer count (matches `q` alone, ignoring facets) — drives the
    // "create?" prompt. Undefined while pending or on error so it never flashes.
    query_count: facets.then((r) => r.data?.query_count).catch(() => undefined),
  };
};
