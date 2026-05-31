<script lang="ts">
  import client from '$lib/api/client';
  import TitleCard from '$lib/components/cards/TitleCard.svelte';
  import ServerPaginatedGrid from '$lib/components/grid/ServerPaginatedGrid.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';
  import type { TitleCardSchema } from '$lib/api/schema';
  import type { TitlesQuery } from './titles-query';

  let {
    initial,
    query,
  }: {
    /** SSR page 1 — seeds the loader so the cards render server-side. */
    initial: { items: TitleCardSchema[]; count: number };
    /** Active filters; reused verbatim for load-more (page 2…N). */
    query: TitlesQuery;
  } = $props();

  // Seeded from the SSR response: page 1 is already present, so `onMount`
  // skips its first fetch and load-more starts at page 2. The parent remounts
  // this component (via `{#key}`) when the filters change, so each mount's
  // `initial` is the fresh server-filtered page 1 — no double-fetch.
  // svelte-ignore state_referenced_locally
  // Seeding once at construction is intentional: the parent remounts this
  // component (via `{#key}`) whenever the filters change, so each instance's
  // `initial` is the fresh server-filtered page 1.
  const loader = createPaginatedLoader(async (page) => {
    const { data } = await client.GET('/api/titles/', {
      params: { query: { ...query, page } },
    });
    return data ?? { items: [], count: 0 };
  }, initial);
</script>

<ServerPaginatedGrid items={loader.items} hasMore={loader.hasMore} loadMore={loader.loadMore}>
  {#snippet children(title)}
    <TitleCard
      slug={title.slug}
      name={title.name}
      thumbnailUrl={title.thumbnail_url}
      manufacturerName={title.manufacturer?.name}
      year={title.year}
    />
  {/snippet}
</ServerPaginatedGrid>
