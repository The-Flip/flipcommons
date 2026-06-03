<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  import type { createPaginatedLoader } from '$lib/paginated-loader.svelte';
  import ServerPaginatedGrid from './ServerPaginatedGrid.svelte';

  let {
    loader,
    heading,
    emptyMessage,
    children,
  }: {
    loader: ReturnType<typeof createPaginatedLoader<T>>;
    heading: string;
    emptyMessage: string;
    children: Snippet<[T]>;
  } = $props();
</script>

{#if loader.loading}
  <p class="empty">Loading…</p>
{:else if loader.error}
  <p class="empty">Failed to load.</p>
{:else if loader.count === 0}
  <p class="empty">{emptyMessage}</p>
{:else}
  <section>
    <h2>{heading} ({loader.count})</h2>
    <ServerPaginatedGrid
      items={loader.items}
      hasMore={loader.hasMore}
      loadMore={loader.loadMore}
      {children}
    />
  </section>
{/if}

<style>
  h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
    text-align: center;
  }
</style>
