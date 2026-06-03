<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

<ul class="sidebar-list">
  {@render children()}
</ul>

<style>
  .sidebar-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
</style>
