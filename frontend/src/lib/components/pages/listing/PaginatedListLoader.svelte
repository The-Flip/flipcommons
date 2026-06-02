<script lang="ts" generics="T extends { slug: string }">
  import type { Snippet } from 'svelte';
  import ServerPaginatedList from '$lib/components/grid/ServerPaginatedList.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';

  /**
   * Inner loader host for `PaginatedListPage`, built fresh each time the parent
   * `{#key}`-remounts it on a search change — so each mount seeds the loader
   * with that search's fresh SSR page 1 (no double-fetch of page 1). Mirrors
   * the titles `TitlesGrid` split: the controller chrome (search box, header)
   * stays mounted while only this loader remounts.
   */
  let {
    initial,
    fetchPage,
    basePath,
    children,
  }: {
    initial: { items: T[]; count: number };
    fetchPage: (page: number) => Promise<{ items: T[]; count: number }>;
    basePath: string;
    children: Snippet<[T]>;
  } = $props();

  // Seeding once at construction is intentional — the parent remounts this via
  // `{#key}` whenever the search changes, so each instance's `initial` is the
  // fresh server-filtered page 1.
  // svelte-ignore state_referenced_locally
  const loader = createPaginatedLoader(fetchPage, initial);
</script>

<ServerPaginatedList
  items={loader.items}
  hasMore={loader.hasMore}
  loadMore={loader.loadMore}
  {basePath}
  {children}
/>
