<script lang="ts">
  import { normalizeText } from '$lib/utils';
  import ComboboxListbox from './dropdown/ComboboxListbox.svelte';
  import SelectedChips from './dropdown/SelectedChips.svelte';
  import FieldGroup from './FieldGroup.svelte';

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
    disabled = false,
    emptyMessage = 'No options available',
  }: {
    options: { value: string; label: string; count?: number }[];
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
     * Render the control inert: the input can't be focused/opened, the clear and
     * tag-remove buttons are hidden, and the mutation handlers no-op. Used by the
     * filter sidebar to hold the control while its options stream in (see `streamed`).
     * Defaults false, so existing consumers are unaffected.
     */
    disabled?: boolean;
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

  // Multi-select chips, resolving each selected value to its option label and
  // dropping any value with no matching option.
  let selectedChips = $derived.by(() => {
    if (!multi || !Array.isArray(selected)) return [];
    return selected.flatMap((value) => {
      const opt = options.find((o) => o.value === value);
      return opt ? [{ value, label: opt.label }] : [];
    });
  });

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
    // When counts aren't shown, the list carries no popularity signal and the
    // caller's order is meaningful (e.g. a taxonomy's editorial `display_order`
    // from the backend) — preserve it. Re-sorting here would silently
    // alphabetize every editor dropdown.
    if (!showCounts) return opts;
    // Count-ranked: non-zero counts first (desc), then zero-count; within each
    // group alphabetical.
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

  function isSelected(value: string): boolean {
    if (multi && Array.isArray(selected)) {
      return selected.includes(value);
    }
    return selected === value;
  }

  function toggle(value: string) {
    if (disabled) return;
    if (multi) {
      const arr = Array.isArray(selected) ? selected : [];
      if (arr.includes(value)) {
        selected = arr.filter((s) => s !== value);
      } else {
        selected = [...arr, value];
      }
    } else {
      selected = selected === value ? null : value;
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
      const opt = options.find((o) => o.value === selected);
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
          if (!isDisabled(opt)) toggle(opt.value);
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

  // `$props.id()` is stable across SSR and hydration — required now that the filter
  // sidebar server-renders this control (a `Math.random()` id would mismatch on hydrate).
  const uid = $props.id();
  const inputId = `${uid}-input`;
  const listboxId = `${uid}-listbox`;
  const errorId = `${uid}-error`;
</script>

{#snippet body()}
  <div class="input-wrap" bind:this={inputWrapEl}>
    <input
      id={inputId}
      bind:this={inputEl}
      type="text"
      role="combobox"
      {disabled}
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
    {#if !multi && selected && !disabled}
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

  {#if multi}
    <SelectedChips chips={selectedChips} {disabled} onremove={toggle} />
  {/if}

  {#snippet optionRow(opt: { value: string; label: string; count?: number })}
    <span class="option-label">{opt.label}</span>
    {#if showCounts && opt.count != null}
      <span class="option-count">({opt.count})</span>
    {/if}
  {/snippet}

  {#if open && inputWrapEl}
    <ComboboxListbox
      rows={filteredOptions}
      {activeIndex}
      {listboxId}
      {multi}
      anchor={inputWrapEl}
      bind:listElement={listEl}
      isSelected={(opt) => isSelected(opt.value)}
      isDisabled={(opt) => isDisabled(opt)}
      onhover={(i) => (activeIndex = i)}
      onselect={(opt) => toggle(opt.value)}
      row={optionRow}
    >
      {#snippet empty()}
        {options.length === 0 ? emptyMessage : 'No matches'}
      {/snippet}
    </ComboboxListbox>
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

  /* The listbox shell (.dropdown/.option/.check/.no-results) lives in
     ComboboxListbox; the M2M chip row in SelectedChips; only the per-row
     content below is styled here. */
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

  .field-error {
    font-size: var(--font-size-0);
    color: var(--color-error-text);
    margin: var(--size-1) 0 0;
  }
</style>
