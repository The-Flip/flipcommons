<script lang="ts">
  let {
    placeholder = '',
    value = $bindable(''),
    oninput,
    onkeydown,
    inputRef = $bindable<HTMLInputElement | undefined>(undefined),
    activeDescendant,
    listboxId,
  }: {
    placeholder?: string;
    value?: string;
    oninput?: (e: Event) => void;
    onkeydown?: (e: KeyboardEvent) => void;
    inputRef?: HTMLInputElement | undefined;
    activeDescendant?: string;
    listboxId?: string;
  } = $props();
</script>

<div class="search-wrap">
  <input
    bind:this={inputRef}
    type="text"
    class="search-input"
    role="combobox"
    aria-label={placeholder}
    aria-expanded={true}
    aria-controls={listboxId}
    aria-activedescendant={activeDescendant}
    aria-autocomplete="list"
    {placeholder}
    {value}
    {oninput}
    {onkeydown}
  />
</div>

<style>
  .search-wrap {
    padding: var(--size-2) var(--size-3);
    border-bottom: 1px solid var(--color-border);
  }

  .search-input {
    width: 100%;
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-1);
    font-family: inherit;
    background-color: var(--color-input-bg);
    color: var(--color-text);
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
  }

  .search-input:focus {
    outline: none;
    border-color: var(--color-input-focus);
    box-shadow: 0 0 0 2px var(--color-input-focus-ring);
  }
</style>
