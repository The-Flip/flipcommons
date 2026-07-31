<script lang="ts" generics="T extends { slug: string }">
  import type { Snippet } from 'svelte';
  import ServerPaginatedList from '$lib/components/collections/list/ServerPaginatedList.svelte';
  import { createPaginatedLoader } from '$lib/paginated-loader.svelte';

  /**
   * Row-list loader host shared by the listing controllers — built fresh each
   * time the parent `{#key}`-remounts it on a filter/search change, so each
   * mount seeds the loader with that query's fresh SSR page 1 (no double-fetch
   * of page 1). The split keeps the controller chrome (search box, sidebar,
   * header) mounted while only this loader remounts.
   *
   * Renders the linked `<ul>` rows (`ServerPaginatedList`, which wraps each row
   * in the `${basePath}/${slug}` link) — hence the `slug` constraint on `T`.
   * Card grids use `PaginatedCardLoader`, whose cards link themselves.
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
