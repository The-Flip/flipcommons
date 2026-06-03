<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    heading,
    note,
    onEdit = undefined,
    children,
  }: { heading: string; note?: string; onEdit?: () => void; children: Snippet } = $props();
</script>

<section class="sidebar-section">
  <h3>
    {heading}
    {#if onEdit}
      <button class="edit-link" type="button" onclick={onEdit}>edit</button>
    {/if}
  </h3>
  {#if note}
    <p class="note">{note}</p>
  {/if}
  {@render children()}
</section>

<style>
  .sidebar-section {
    padding-bottom: var(--size-3);
    border-bottom: 1px solid var(--color-border-soft);
  }

  .sidebar-section h3 {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    font-size: var(--font-size-1);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-1);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .edit-link {
    font-size: var(--font-size-00, 0.75rem);
    font-weight: 400;
    color: var(--color-text-muted);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    text-transform: none;
    letter-spacing: normal;
  }

  .edit-link::before {
    content: '[';
  }

  .edit-link::after {
    content: ']';
  }

  .edit-link:hover {
    color: var(--color-link);
  }

  .note {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-2);
  }
</style>
