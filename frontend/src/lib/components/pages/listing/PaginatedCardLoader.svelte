<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  import ServerPaginatedGrid from '$lib/components/collections/grid/ServerPaginatedGrid.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';

  /**
   * Card-grid twin of `PaginatedListLoader`: the loader host the listing
   * controllers `{#key}`-remount on a filter/search change so each mount seeds
   * with that query's fresh SSR page 1 (no double-fetch of page 1). Unlike the
   * row host it puts no shape constraint on `T` — each card supplies its own
   * link, so no `slug`/`basePath` is needed here.
   */
  let {
    initial,
    fetchPage,
    children,
  }: {
    initial: { items: T[]; count: number };
    fetchPage: (page: number) => Promise<{ items: T[]; count: number }>;
    children: Snippet<[T]>;
  } = $props();

  // Seeding once at construction is intentional — the parent remounts this via
  // `{#key}` whenever the search changes, so each instance's `initial` is the
  // fresh server-filtered page 1.
  // svelte-ignore state_referenced_locally
  const loader = createPaginatedLoader(fetchPage, initial);
</script>

<ServerPaginatedGrid
  items={loader.items}
  hasMore={loader.hasMore}
  loadMore={loader.loadMore}
  {children}
/>
