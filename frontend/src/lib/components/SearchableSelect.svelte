<script lang="ts">
  import { floating } from '$lib/actions/floating';
  import { normalizeText } from '$lib/utils';
  import FieldGroup from './form/FieldGroup.svelte';

  let {
    options,
    selected = $bindable(null),
    multi = false,
    allowZeroCount = false,
    showCounts = true,
    placeholder = 'Search...',
    label = '',
    error = '',
    compact = false,
    emptyMessage = 'No options available',
  }: {
    options: { slug: string; label: string; count?: number }[];
    selected?: string | string[] | null;
    multi?: boolean;
    allowZeroCount?: boolean;
    showCounts?: boolean;
    placeholder?: string;
    label?: string;
    error?: string;
    /** Use the de-emphasized filter-sidebar label treatment instead of the form FieldGroup. */
    compact?: boolean;
    /**
     * Shown when there are **no options at all** (a distinct cause from a search
     * that filtered the list to empty, which always shows "No matches"). Lets a
     * caller explain why the list is empty — e.g. a faceted sidebar pruned every
     * value under the current filters.
     */
    emptyMessage?: string;
  } = $props();

  function isDisabled(opt: { count?: number }): boolean {
    return !allowZeroCount && opt.count === 0;
  }

  let query = $state('');
  let open = $state(false);
  let activeIndex = $state(-1);
  let inputEl: HTMLInputElement | undefined = $state();
  let inputWrapEl: HTMLDivElement | undefined = $state();
  let listEl: HTMLUListElement | undefined = $state();

  let filteredOptions = $derived.by(() => {
    const q = normalizeText(query.trim());
    let opts = options;
    if (q) {
      opts = opts.filter((o) => normalizeText(o.label).includes(q));
    }
    // Sort: non-zero counts first (desc), then zero-count; within each group alphabetical
    return opts.slice().sort((a, b) => {
      const ac = a.count ?? 0;
      const bc = b.count ?? 0;
      if (ac === 0 && bc !== 0) return 1;
      if (ac !== 0 && bc === 0) return -1;
      if (ac !== bc) return bc - ac;
      return a.label.localeCompare(b.label);
    });
  });

  $effect(() => {
    if (!open || activeIndex < 0 || !listEl) return;
    listEl.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  });

  function isSelected(slug: string): boolean {
    if (multi && Array.isArray(selected)) {
      return selected.includes(slug);
    }
    return selected === slug;
  }

  function toggle(slug: string) {
    if (multi) {
      const arr = Array.isArray(selected) ? selected : [];
      if (arr.includes(slug)) {
        selected = arr.filter((s) => s !== slug);
      } else {
        selected = [...arr, slug];
      }
    } else {
      selected = selected === slug ? null : slug;
      open = false;
      query = '';
    }
  }

  function selectedLabel(): string {
    if (multi) {
      // In multi mode, selections are already rendered as chips below the
      // input. Showing a single selected label inside the input reads like
      // a current search query, so suppress it — let the chip speak for
      // the selection and keep the input as a search affordance.
      const arr = Array.isArray(selected) ? selected : [];
      if (arr.length > 1) return `${arr.length} selected`;
      return '';
    }
    if (typeof selected === 'string') {
      const opt = options.find((o) => o.slug === selected);
      return opt?.label ?? '';
    }
    return '';
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        open = true;
        activeIndex = 0;
        e.preventDefault();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, filteredOptions.length - 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        break;
      case 'Enter':
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < filteredOptions.length) {
          const opt = filteredOptions[activeIndex];
          if (!isDisabled(opt)) toggle(opt.slug);
        }
        break;
      case 'Escape':
        if (open) {
          e.preventDefault();
          e.stopPropagation();
          open = false;
          query = '';
          inputEl?.blur();
        }
        break;
    }
  }

  function handleFocus() {
    open = true;
    activeIndex = -1;
  }

  // Reset activeIndex when filtered options change
  $effect(() => {
    void filteredOptions;
    activeIndex = -1;
  });

  // Click or focus outside to close
  $effect(() => {
    if (!open) return;
    function isOutside(target: Node | null): boolean {
      if (!target) return true;
      const insideSelect = inputEl?.closest('.searchable-select')?.contains(target);
      // The dropdown is portaled out of `.searchable-select`, so check it too.
      const insideDropdown = listEl?.contains(target);
      return !insideSelect && !insideDropdown;
    }
    function close() {
      open = false;
      query = '';
    }
    function onPointerDown(e: PointerEvent) {
      if (isOutside(e.target as Node)) close();
    }
    function onFocusIn(e: FocusEvent) {
      if (isOutside(e.target as Node)) close();
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('focusin', onFocusIn);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('focusin', onFocusIn);
    };
  });

  const inputId = `searchable-select-${Math.random().toString(36).slice(2, 8)}`;
  const listboxId = `listbox-${Math.random().toString(36).slice(2, 8)}`;
  const errorId = `${inputId}-error`;
</script>

{#snippet body()}
  <div class="input-wrap" bind:this={inputWrapEl}>
    <input
      id={inputId}
      bind:this={inputEl}
      type="text"
      role="combobox"
      aria-expanded={open}
      aria-controls={listboxId}
      aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? errorId : undefined}
      {placeholder}
      value={open ? query : selectedLabel() || ''}
      oninput={(e) => {
        query = e.currentTarget.value;
        if (!open) open = true;
      }}
      onfocus={handleFocus}
      onkeydown={handleKeydown}
    />
    {#if !multi && selected}
      <button
        class="clear-btn"
        aria-label="Clear selection"
        onclick={(e) => {
          e.stopPropagation();
          selected = null;
          query = '';
        }}
      >
        ×
      </button>
    {/if}
  </div>

  {#if multi && Array.isArray(selected) && selected.length > 0}
    <div class="selected-tags">
      {#each selected as slug (slug)}
        {@const opt = options.find((o) => o.slug === slug)}
        {#if opt}
          <span class="tag">
            {opt.label}
            <button
              class="tag-remove"
              aria-label={`Remove ${opt.label}`}
              onclick={() => toggle(slug)}
            >
              ×
            </button>
          </span>
        {/if}
      {/each}
    </div>
  {/if}

  {#if open && inputWrapEl}
    <ul
      bind:this={listEl}
      id={listboxId}
      role="listbox"
      class="dropdown"
      use:floating={{
        anchor: inputWrapEl,
        placement: 'bottom-start',
        matchAnchorWidth: true,
        maxHeight: 'available',
      }}
    >
      {#each filteredOptions as opt, i (opt.slug)}
        <li
          id={`${listboxId}-${i}`}
          role="option"
          aria-selected={isSelected(opt.slug)}
          aria-disabled={isDisabled(opt)}
          data-active={i === activeIndex}
          class="option"
          class:selected={isSelected(opt.slug)}
          class:disabled={isDisabled(opt)}
          class:active={i === activeIndex}
          onpointerenter={() => {
            if (!isDisabled(opt)) activeIndex = i;
          }}
          onpointerdown={(e) => {
            e.preventDefault();
            if (!isDisabled(opt)) toggle(opt.slug);
          }}
        >
          {#if multi}
            <span class="check">{isSelected(opt.slug) ? '✓' : ''}</span>
          {/if}
          <span class="option-label">{opt.label}</span>
          {#if showCounts && opt.count != null}
            <span class="option-count">({opt.count})</span>
          {/if}
        </li>
      {:else}
        <li class="no-results">{options.length === 0 ? emptyMessage : 'No matches'}</li>
      {/each}
    </ul>
  {/if}
{/snippet}

{#if compact}
  <div class="searchable-select">
    {#if label}
      <label class="filter-label" for={inputId}>{label}</label>
    {/if}
    {@render body()}
    {#if error}
      <p class="field-error" id={errorId} role="alert">{error}</p>
    {/if}
  </div>
{:else}
  <FieldGroup {label} id={inputId} {error}>
    {#snippet children(_id, _errorId)}
      <div class="searchable-select">
        {@render body()}
      </div>
    {/snippet}
  </FieldGroup>
{/if}

<style>
  .filter-label {
    display: block;
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin-bottom: var(--size-1);
  }

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

  .option-label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .option-count {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    flex-shrink: 0;
  }

  .no-results {
    padding: var(--size-3);
    color: var(--color-text-muted);
    text-align: center;
    font-size: var(--font-size-1);
  }

  .field-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: var(--size-1) 0 0;
  }
</style>
