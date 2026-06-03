<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    onback,
    children,
  }: {
    onback?: () => void;
    children: Snippet;
  } = $props();
</script>

<div class="dropdown-header">
  {#if onback}
    <button
      class="back-btn"
      aria-label="Back"
      onpointerdown={(e) => {
        e.preventDefault();
        onback?.();
      }}
    >
      &larr;
    </button>
  {/if}
  {@render children()}
</div>

<style>
  .dropdown-header {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    border-bottom: 1px solid var(--color-border);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .back-btn {
    background: none;
    border: none;
    color: var(--color-text-muted);
    cursor: pointer;
    padding: 0;
    font-size: var(--font-size-1);
    line-height: 1;
    flex-shrink: 0;
  }

  .back-btn:hover {
    color: var(--color-text);
  }
</style>
