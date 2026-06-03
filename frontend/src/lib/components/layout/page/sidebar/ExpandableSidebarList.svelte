<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';

  import SidebarList from './SidebarList.svelte';

  let {
    items,
    limit = 10,
    key,
    children,
  }: {
    items: T[];
    limit?: number;
    key?: (item: T) => string | number;
    children: Snippet<[T]>;
  } = $props();

  let expanded = $state(false);
  let visible = $derived(expanded ? items : items.slice(0, limit));
  let hasMore = $derived(items.length > limit);

  // Reset expanded state when navigating to a different entity.
  let itemsRef = $derived(items);
  $effect(() => {
    void itemsRef;
    expanded = false;
  });
</script>

<SidebarList>
  {#each visible as item, i (key ? key(item) : i)}
    {@render children(item)}
  {/each}
</SidebarList>
{#if hasMore}
  <button class="show-toggle" onclick={() => (expanded = !expanded)}>
    {expanded ? 'Show fewer' : `Show all ${items.length}`}
  </button>
{/if}

<style>
  .show-toggle {
    background: none;
    border: none;
    color: var(--color-link);
    font-size: var(--font-size-0);
    padding: var(--size-1) 0 0;
    cursor: pointer;
  }

  .show-toggle:hover {
    text-decoration: underline;
  }
</style>
