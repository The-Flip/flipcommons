<script lang="ts">
  import type { Snippet } from 'svelte';

  type Variant = 'loading' | 'empty' | 'error';

  let { variant, children }: { variant: Variant; children: Snippet } = $props();
</script>

{#if variant === 'loading'}
  <p class="status" role="status" aria-live="polite" aria-busy="true">
    {@render children()}
  </p>
{:else if variant === 'error'}
  <p class="status error" role="alert">{@render children()}</p>
{:else}
  <p class="status">{@render children()}</p>
{/if}

<style>
  .status {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    padding: var(--size-8) 0;
    text-align: center;
  }

  .error {
    color: var(--color-error-text);
  }
</style>
