<script lang="ts">
  import { faMagnifyingGlass } from '@fortawesome/free-solid-svg-icons';
  import FaIcon from './FaIcon.svelte';

  let {
    value = $bindable(''),
    placeholder = 'Search...',
    disabled = false,
    autofocus = false,
  }: {
    value?: string;
    placeholder?: string;
    disabled?: boolean;
    autofocus?: boolean;
  } = $props();
</script>

<form class="search-box" onsubmit={(e) => e.preventDefault()}>
  <span class="search-icon"><FaIcon icon={faMagnifyingGlass} size="1rem" /></span>
  <!-- svelte-ignore a11y_autofocus -->
  <input type="search" {placeholder} aria-label={placeholder} bind:value {disabled} {autofocus} />
</form>

<style>
  .search-box {
    position: relative;
    max-width: 36rem;
    margin: 0 auto var(--size-4);
  }

  .search-icon {
    position: absolute;
    left: var(--size-4);
    top: 50%;
    transform: translateY(-50%);
    color: var(--color-text-muted);
    pointer-events: none;
    display: flex;
  }

  input[type='search'] {
    padding: var(--size-3) var(--size-4) var(--size-3) var(--size-9);
    font-size: var(--font-size-2);
    border-radius: var(--radius-3);
    transition:
      border-color 0.15s var(--ease-2),
      box-shadow 0.15s var(--ease-2);
  }
</style>
