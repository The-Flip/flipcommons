import { error } from '@sveltejs/kit';
import { createServerClient } from '$lib/api/server';
import { queryFromUrl } from './titles-query';
import type { PageServerLoad } from './$types';

/**
 * SSR load for /titles. The cards are **awaited** so page 1 lands in the server
 * HTML (crawlable, ~16 ms server time). The facet option lists are returned as
 * an **unawaited promise** — SvelteKit streams them down the same chunked
 * response after the cards, so the count badges (~107 ms, neither a crawler nor
 * the first paint needs them) don't block the grid. The page renders the facet
 * promise with `{#await}`.
 */
export const load: PageServerLoad = async ({ fetch, url, request }) => {
  const client = createServerClient(fetch, url, request);
  const query = queryFromUrl(url);

  const cards = await client.GET('/api/titles/', {
    params: { query: { ...query, page: 1 } },
  });
  // Cards are the critical path: a backend failure must surface as an error
  // page, not degrade to an empty "0 titles" success (which would also mislead
  // the create prompt on a query).
  if (!cards.data) {
    throw error(cards.response.status || 500, 'Failed to load titles');
  }

  const facets = client.GET('/api/pages/titles', { params: { query } });

  return {
    items: cards.data.items,
    count: cards.data.count,
    // The query that produced page 1 — the client grid reuses it for load-more.
    query,
    // Unawaited → streamed after the cards. Resolves to undefined (never
    // rejects) on a facet-endpoint error, so the sidebar simply stays on its
    // skeleton instead of surfacing an unhandled rejection — the cards, which
    // are the critical path, already rendered.
    filter_options: facets.then((r) => r.data?.filter_options).catch(() => undefined),
    // Query-only title count (matches `q` alone, ignoring facets) — streamed
    // alongside the facets and drives the "create?" prompt. Same request as
    // above; undefined while pending or on error so the prompt never flashes.
    query_count: facets.then((r) => r.data?.query_count).catch(() => undefined),
  };
};
