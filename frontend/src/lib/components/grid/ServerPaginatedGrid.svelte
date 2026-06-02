<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  import CardGrid from './CardGrid.svelte';
  import InfiniteScroll from './InfiniteScroll.svelte';

  let {
    items,
    hasMore,
    loadMore,
    children,
  }: {
    items: T[];
    hasMore: boolean;
    loadMore: () => void;
    children: Snippet<[T]>;
  } = $props();
</script>

<InfiniteScroll {hasMore} onSentinel={loadMore}>
  <CardGrid>
    {#each items as item (item)}
      {@render children(item)}
    {/each}
  </CardGrid>
</InfiniteScroll>
