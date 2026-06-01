<script lang="ts">
  import client from '$lib/api/client';
  import ManufacturerCard from '$lib/components/cards/ManufacturerCard.svelte';
  import ServerPaginatedGrid from '$lib/components/grid/ServerPaginatedGrid.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';
  import type { ManufacturerCardSchema } from '$lib/api/schema';
  import type { ManufacturersQuery } from './manufacturers-query';

  let {
    initial,
    query,
  }: {
    /** SSR page 1 — seeds the loader so the cards render server-side. */
    initial: { items: ManufacturerCardSchema[]; count: number };
    /** Active filters; reused verbatim for load-more (page 2…N). */
    query: ManufacturersQuery;
  } = $props();

  // Seeded from the SSR response: page 1 is already present, so the loader skips its
  // first fetch and load-more starts at page 2. The parent remounts this component
  // (via `{#key}`) when the filters change, so each mount's `initial` is the fresh
  // server-filtered page 1 — no double-fetch.
  // svelte-ignore state_referenced_locally
  const loader = createPaginatedLoader(async (page) => {
    const { data } = await client.GET('/api/manufacturers/', {
      params: { query: { ...query, page } },
    });
    return data ?? { items: [], count: 0 };
  }, initial);
</script>

<ServerPaginatedGrid items={loader.items} hasMore={loader.hasMore} loadMore={loader.loadMore}>
  {#snippet children(mfr)}
    <ManufacturerCard
      slug={mfr.slug}
      name={mfr.name}
      thumbnailUrl={mfr.thumbnail_url}
      modelCount={mfr.model_count}
    />
  {/snippet}
</ServerPaginatedGrid>
