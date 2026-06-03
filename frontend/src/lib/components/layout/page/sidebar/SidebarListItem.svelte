<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

<li class="sidebar-list-item">
  {@render children()}
</li>

<style>
  .sidebar-list-item {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }

  .sidebar-list-item:not(:last-child) {
    border-bottom: 1px solid var(--color-border-soft);
  }
</style>
