<!--
@component
Card row for batch list editors with pending-change visuals: an accent bar and
status chip for added/changed rows, strike-through plus Undo for removed rows.
Shared so every list editor (relationships, people) renders unsaved edits
identically — the footer Save stays the single commit point.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    status = 'unchanged',
    onundo = undefined,
    children,
    actions = undefined,
  }: {
    status?: 'unchanged' | 'added' | 'changed' | 'removed';
    /** Restore a removed row; rendered as the row's only action while removed. */
    onundo?: () => void;
    /** The row's content (text or controls). */
    children: Snippet;
    /** Row actions (edit / remove buttons); hidden while the row is removed. */
    actions?: Snippet;
  } = $props();

  const chipLabels = { added: 'New', changed: 'Changed', removed: 'Removed' } as const;
</script>

<div class="dirty-row {status}">
  <div class="content" class:struck={status === 'removed'}>
    {@render children()}
  </div>
  {#if status !== 'unchanged'}
    <span class="chip {status}">{chipLabels[status]}</span>
  {/if}
  {#if status === 'removed'}
    {#if onundo}
      <button type="button" class="undo-btn" onclick={onundo}>Undo</button>
    {/if}
  {:else if actions}
    {@render actions()}
  {/if}
</div>

<style>
  .dirty-row {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    border-left-width: 3px;
  }

  .dirty-row.added,
  .dirty-row.changed {
    border-left-color: var(--color-accent, var(--color-text-muted));
  }

  .dirty-row.removed {
    border-left-color: var(--color-error-text);
    opacity: 0.7;
  }

  .content {
    flex: 1;
    min-width: 0;
  }

  .content.struck {
    text-decoration: line-through;
    color: var(--color-text-muted);
  }

  .chip {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-round, 999px);
    padding: 0.1rem 0.55rem;
    white-space: nowrap;
  }

  .chip.removed {
    color: var(--color-error-text);
    border-color: var(--color-error-text);
  }

  .undo-btn {
    background: none;
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-1);
    padding: 0.3rem 0.6rem;
    cursor: pointer;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .undo-btn:hover {
    color: var(--color-text);
    border-color: var(--color-text-muted);
  }
</style>
