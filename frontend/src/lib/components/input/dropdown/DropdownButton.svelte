<!-- @component Submit/action button styled as dropdown form chrome. -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';

  let { children, ...rest }: HTMLButtonAttributes & { children: Snippet } = $props();
</script>

<button class="dropdown-button" {...rest}>{@render children()}</button>

<style>
  .dropdown-button {
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-1);
    font-family: inherit;
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background-color: var(--color-input-focus-ring);
    color: var(--color-text);
    cursor: pointer;
  }

  .dropdown-button:hover:not(:disabled) {
    border-color: var(--color-input-focus);
  }

  .dropdown-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
