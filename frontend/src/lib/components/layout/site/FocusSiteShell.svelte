<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

<main class="focus-content">
  {@render children()}
</main>

<style>
  .focus-content {
    flex: 1;
    width: 100%;
  }
</style>
