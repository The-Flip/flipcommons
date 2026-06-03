<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

<p class="last-updated">{@render children()}</p>

<style>
  .last-updated {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    margin-bottom: var(--size-6);
  }
</style>
