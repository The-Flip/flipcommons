<!--
@component
Internal combobox core: the input, portaled listbox, a11y, keyboard nav and
debounced async typeahead against the entity-autocomplete endpoint, with a
label cache so a saved value renders without a search. Not used directly —
wrapped for single- vs multi-selection.
-->
<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import {
    autocompleteEntities,
    AUTOCOMPLETE_RESULT_LIMIT,
    type EntityOption,
  } from '$lib/api/entity-autocomplete';
  import ComboboxListbox from '$lib/components/input/dropdown/ComboboxListbox.svelte';
  import { createDebouncedSearch } from '$lib/components/input/dropdown/search-helpers';
  import FieldGroup from '$lib/components/input/FieldGroup.svelte';

  let {
    type,
    multi = false,
    selectedValues,
    initialOptions = [],
    exclude = [],
    label = '',
    placeholder = 'Search...',
    error = '',
    disabled = false,
    required = false,
    onToggle,
    onRemove,
    onClear,
  }: {
    /** Registry key the endpoint searches (`manufacturer`, `title`, …). */
    type: string;
    /** Single = 0/1, multi = N. Drives row highlight + chip/clear chrome. */
    multi?: boolean;
    selectedValues: string[];
    /** Rows to pre-seed the label cache so saved values render with no search. */
    initialOptions?: EntityOption[];
    /** Values to drop from the listbox (e.g. the current record, to forbid self-reference). */
    exclude?: string[];
    label?: string;
    placeholder?: string;
    error?: string;
    disabled?: boolean;
    /** Single only: hide the clear (×) so the field can't be emptied. */
    required?: boolean;
    /** A listbox row was activated. Wrapper updates its own selection. */
    onToggle: (row: EntityOption) => void;
    /** Multi only: a chip's remove (×) was pressed. */
    onRemove?: (value: string) => void;
    /** Single only: the clear (×) was pressed. */
    onClear?: () => void;
  } = $props();

  // value → label, seeded from initial selection and grown from every search
  // response and toggled row, so chips and the single selected label always
  // have text without re-fetching.
  const labelCache = new SvelteMap<string, EntityOption>();
  function remember(rows: EntityOption[]) {
    for (const row of rows) labelCache.set(row.value, row);
  }
  // Seed synchronously so the saved label paints on the first render (no slug
  // flash). `untrack` marks this as a deliberate one-time read of the prop,
  // silencing the `state_referenced_locally` warning; the $effect below picks
  // up any later changes.
  untrack(() => remember(initialOptions));
  // Re-seed if a parent swaps the saved selection on a live instance (editors
  // are CSR, so this happens without a remount). The cache only grows, so
  // re-running is harmless.
  $effect(() => {
    remember(initialOptions);
  });

  let query = $state('');
  let open = $state(false);
  let loading = $state(false);
  let rows = $state<EntityOption[]>([]);
  let activeIndex = $state(-1);
  let inputEl: HTMLInputElement | undefined = $state();
  let inputWrapEl: HTMLDivElement | undefined = $state();
  let listEl: HTMLUListElement | undefined = $state();

  // A full page from the endpoint means the set was capped and more likely
  // exist — hint the user to type rather than scroll for them. Tracked from the
  // raw response count (before `exclude` trims a row), so dropping the self-row
  // from a full page doesn't read as "not capped".
  let capped = $state(false);

  const search = createDebouncedSearch(
    async (q: string) => {
      try {
        return await autocompleteEntities(type, q);
      } catch {
        // Degrade to empty results rather than hang on "Searching…" (and avoid
        // an unhandled rejection). A transient failure recovers on the next
        // keystroke; a misconfigured type reads as "No matches".
        return [];
      }
    },
    (results) => {
      remember(results);
      capped = results.length >= AUTOCOMPLETE_RESULT_LIMIT;
      // Cache every row (label lookups), but never show an excluded value —
      // e.g. the current record, which can't reference itself.
      rows = exclude.length ? results.filter((r) => !exclude.includes(r.value)) : results;
      loading = false;
    },
  );

  function runSearch(q: string) {
    loading = true;
    search.search(q);
  }

  function closeDropdown() {
    open = false;
    query = '';
    loading = false;
    // Drop any pending/in-flight search so a late response can't write rows
    // back into a closed control.
    search.cancel();
  }

  // Same guard for teardown: cancel a debounce armed right before unmount.
  onDestroy(search.cancel);

  function isSelected(value: string): boolean {
    return selectedValues.includes(value);
  }

  function labelOf(value: string): string {
    return labelCache.get(value)?.label ?? value;
  }

  function selectRow(row: EntityOption) {
    if (disabled) return;
    remember([row]);
    onToggle(row);
    if (!multi) closeDropdown();
  }

  /** Text shown in the input when it isn't being typed into. */
  function closedInputText(): string {
    if (multi) {
      // In multi mode selections are chips below the input; echoing one inside
      // the input reads like a stale search query, so keep it empty.
      return selectedValues.length > 1 ? `${selectedValues.length} selected` : '';
    }
    return selectedValues.length === 1 ? labelOf(selectedValues[0]) : '';
  }

  function handleFocus() {
    if (disabled) return;
    open = true;
    activeIndex = -1;
    runSearch(query);
  }

  function handleInput(value: string) {
    query = value;
    if (!open) open = true;
    runSearch(value);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        // Open with no active row (like focus): results are async, so a row-0
        // highlight set now would be cleared when they arrive anyway.
        open = true;
        activeIndex = -1;
        runSearch(query);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, rows.length - 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        break;
      case 'Enter':
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < rows.length) selectRow(rows[activeIndex]);
        break;
      case 'Escape':
        e.preventDefault();
        e.stopPropagation();
        closeDropdown();
        inputEl?.blur();
        break;
    }
  }

  // Keep the active row scrolled into view as the keyboard moves it.
  $effect(() => {
    if (!open || activeIndex < 0 || !listEl) return;
    listEl.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  });

  // Reset highlight whenever the result set changes.
  $effect(() => {
    void rows;
    activeIndex = -1;
  });

  // Close on pointer/focus outside (the listbox is portaled, so check it too).
  $effect(() => {
    if (!open) return;
    function isOutside(target: Node | null): boolean {
      if (!target) return true;
      const insideSelect = inputEl?.closest('.entity-combobox')?.contains(target);
      const insideDropdown = listEl?.contains(target);
      return !insideSelect && !insideDropdown;
    }
    function onPointerDown(e: PointerEvent) {
      if (isOutside(e.target as Node)) closeDropdown();
    }
    function onFocusIn(e: FocusEvent) {
      if (isOutside(e.target as Node)) closeDropdown();
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('focusin', onFocusIn);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('focusin', onFocusIn);
    };
  });

  // Stable across SSR/hydrate (a random id would mismatch).
  const uid = $props.id();
  const inputId = `${uid}-input`;
  const listboxId = `${uid}-listbox`;
</script>

<FieldGroup {label} id={inputId} {error}>
  {#snippet children(_id, errorId)}
    <div class="entity-combobox">
      <div class="input-wrap" bind:this={inputWrapEl}>
        <input
          id={inputId}
          bind:this={inputEl}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          autocomplete="off"
          {disabled}
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          {placeholder}
          value={open ? query : closedInputText()}
          oninput={(e) => handleInput(e.currentTarget.value)}
          onfocus={handleFocus}
          onkeydown={handleKeydown}
        />
        {#if !multi && selectedValues.length === 1 && !required && !disabled}
          <button
            class="clear-btn"
            aria-label="Clear selection"
            onclick={(e) => {
              e.stopPropagation();
              query = '';
              onClear?.();
            }}
          >
            ×
          </button>
        {/if}
      </div>

      {#if multi && selectedValues.length > 0}
        <div class="selected-tags">
          {#each selectedValues as value (value)}
            <span class="tag">
              {labelOf(value)}
              <button
                class="tag-remove"
                aria-label={`Remove ${labelOf(value)}`}
                {disabled}
                onclick={() => !disabled && onRemove?.(value)}
              >
                ×
              </button>
            </span>
          {/each}
        </div>
      {/if}

      {#snippet optionRow(r: EntityOption)}
        <span class="option-text">
          <span class="option-label">{r.label}</span>
          {#if r.sublabel}
            <span class="option-sublabel">{r.sublabel}</span>
          {/if}
        </span>
      {/snippet}

      {#snippet cappedHint()}
        Showing first {rows.length} — type to search
      {/snippet}

      {#if open && inputWrapEl}
        <ComboboxListbox
          {rows}
          {activeIndex}
          {listboxId}
          {multi}
          anchor={inputWrapEl}
          bind:listElement={listEl}
          isSelected={(r) => isSelected(r.value)}
          onhover={(i) => (activeIndex = i)}
          onselect={(r) => selectRow(r)}
          row={optionRow}
          footer={capped ? cappedHint : undefined}
        >
          {#snippet empty()}
            {loading ? 'Searching…' : 'No matches'}
          {/snippet}
        </ComboboxListbox>
      {/if}
    </div>
  {/snippet}
</FieldGroup>

<style>
  .input-wrap {
    position: relative;
  }

  input {
    transition:
      border-color 0.15s var(--ease-2),
      box-shadow 0.15s var(--ease-2);
  }

  .clear-btn {
    position: absolute;
    right: var(--size-2);
    top: 50%;
    transform: translateY(-50%);
    background: none;
    border: none;
    color: var(--color-text-muted);
    cursor: pointer;
    font-size: var(--font-size-2);
    padding: 0 var(--size-1);
    line-height: 1;
  }

  .clear-btn:hover {
    color: var(--color-text);
  }

  .selected-tags {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-1);
    margin-top: var(--size-1);
  }

  .tag {
    display: inline-flex;
    align-items: center;
    gap: var(--size-1);
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-0);
    background-color: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
  }

  .tag-remove {
    background: none;
    border: none;
    color: var(--color-text-muted);
    cursor: pointer;
    padding: 0;
    font-size: var(--font-size-1);
    line-height: 1;
  }

  .tag-remove:hover {
    color: var(--color-error-text);
  }

  /* The listbox shell (.dropdown/.option/.check/.no-results) lives in
     ComboboxListbox; only the per-row content below is styled here. */
  .option-text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  .option-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .option-sublabel {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
