<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  import CardGrid from './CardGrid.svelte';
  import InfiniteScroll from '$lib/components/collections/InfiniteScroll.svelte';

  const BATCH_SIZE = 100;

  let {
    items,
    entityName = 'result',
    entityNamePlural = `${entityName}s`,
    showCount = true,
    children,
  }: {
    items: T[];
    entityName?: string;
    entityNamePlural?: string;
    showCount?: boolean;
    children: Snippet<[T]>;
  } = $props();

  let visibleCount = $state(BATCH_SIZE);

  let visibleItems = $derived(items.slice(0, visibleCount));
  let hasMore = $derived(visibleCount < items.length);
  let countLabel = $derived(
    `${items.length.toLocaleString()} ${items.length === 1 ? entityName : entityNamePlural}`,
  );

  // Reset visible count when items change
  $effect(() => {
    void items;
    visibleCount = BATCH_SIZE;
  });
</script>

{#if showCount}
  <p class="count">{countLabel}</p>
{/if}

<InfiniteScroll {hasMore} onSentinel={() => (visibleCount += BATCH_SIZE)}>
  <CardGrid>
    {#each visibleItems as item (item)}
      {@render children(item)}
    {/each}
  </CardGrid>
</InfiniteScroll>

<style>
  .count {
    text-align: center;
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
    margin-bottom: var(--size-4);
  }
</style>
