<!--
@component
Presentational listbox shell: the portaled `role="listbox"`, option chrome
(active/selected/disabled states, the multi check column) and empty-state row.
Behavior (filtering, open/close, keyboard nav) and per-row content (a snippet,
styled by the parent's scoped CSS) stay with the parent.
-->
<script lang="ts" generics="Row extends { value: string }">
  import type { Snippet } from 'svelte';
  import { floating } from '$lib/actions/floating';

  let {
    rows,
    activeIndex,
    listboxId,
    anchor,
    multi = false,
    isSelected,
    isDisabled = () => false,
    onhover,
    onselect,
    row,
    empty,
    listElement = $bindable(),
  }: {
    rows: Row[];
    activeIndex: number;
    /** Id of the `<ul>`; option ids are `${listboxId}-${index}` (parent's `aria-activedescendant` matches). */
    listboxId: string;
    /** Element the dropdown is anchored/width-matched to (the input wrap). */
    anchor: HTMLElement;
    /** Render the leading check column and `aria-selected`. */
    multi?: boolean;
    isSelected: (row: Row) => boolean;
    /** Disabled rows render inert and don't fire hover/select on pointer. */
    isDisabled?: (row: Row) => boolean;
    onhover: (index: number) => void;
    onselect: (row: Row) => void;
    /** Per-row content, rendered after the check column. */
    row: Snippet<[Row]>;
    /** Content of the single no-results row when `rows` is empty. */
    empty: Snippet;
    /** The `<ul>` node, exposed so the parent can scroll the active row and detect outside clicks. */
    listElement?: HTMLUListElement;
  } = $props();
</script>

<ul
  bind:this={listElement}
  id={listboxId}
  role="listbox"
  class="dropdown"
  use:floating={{
    anchor,
    placement: 'bottom-start',
    matchAnchorWidth: true,
    maxHeight: 'available',
  }}
>
  {#each rows as r, i (r.value)}
    {@const disabled = isDisabled(r)}
    <li
      id={`${listboxId}-${i}`}
      role="option"
      aria-selected={isSelected(r)}
      aria-disabled={disabled}
      data-active={i === activeIndex}
      class="option"
      class:selected={isSelected(r)}
      class:active={i === activeIndex}
      class:disabled
      onpointerenter={() => {
        if (!disabled) onhover(i);
      }}
      onpointerdown={(e) => {
        e.preventDefault();
        if (!disabled) onselect(r);
      }}
    >
      {#if multi}
        <span class="check">{isSelected(r) ? '✓' : ''}</span>
      {/if}
      {@render row(r)}
    </li>
  {:else}
    <li class="no-results">{@render empty()}</li>
  {/each}
</ul>

<style>
  .dropdown {
    z-index: var(--z-dropdown);
    overflow-y: auto;
    background-color: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
    box-shadow: var(--shadow-popover);
    list-style: none;
    padding: var(--size-1) 0;
    margin: 0;
  }

  .option {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    font-size: var(--font-size-1);
  }

  .option.active {
    background-color: var(--color-input-focus-ring);
  }

  .option.selected {
    font-weight: 600;
  }

  .option.disabled {
    color: var(--color-text-muted);
    opacity: 0.5;
    cursor: default;
  }

  .check {
    width: 1rem;
    text-align: center;
    flex-shrink: 0;
  }

  .no-results {
    padding: var(--size-3);
    color: var(--color-text-muted);
    text-align: center;
    font-size: var(--font-size-1);
  }
</style>
