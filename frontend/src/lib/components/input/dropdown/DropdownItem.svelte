<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    id,
    active = false,
    onselect,
    onhover,
    children,
  }: {
    id?: string;
    active?: boolean;
    onselect: () => void;
    onhover?: () => void;
    children: Snippet;
  } = $props();
</script>

<div
  {id}
  role="option"
  tabindex="-1"
  aria-selected={active}
  data-active={active}
  class="dropdown-item"
  class:active
  onpointerdown={(e) => {
    e.preventDefault();
    onselect();
  }}
  onpointermove={() => onhover?.()}
>
  {@render children()}
</div>

<style>
  .dropdown-item {
    display: flex;
    align-items: baseline;
    gap: var(--size-2);
    padding: var(--size-2) var(--size-3);
    cursor: pointer;
    font-size: var(--font-size-1);
  }

  .dropdown-item.active {
    background-color: var(--color-input-focus-ring);
  }
</style>
