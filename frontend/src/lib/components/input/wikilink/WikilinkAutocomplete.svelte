<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { fetchLinkTypes, searchLinkTargets } from '$lib/api/link-types';
  import type { LinkType, LinkTarget } from '$lib/api/link-types';
  import { formatLinkText } from './wikilink-helpers';
  import { createDebouncedSearch } from '$lib/components/input/dropdown/search-helpers';
  import CitationAutocomplete from '$lib/components/input/citation/CitationAutocomplete.svelte';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import DropdownItem from '$lib/components/input/dropdown/DropdownItem.svelte';
  import DropdownSearchInput from '$lib/components/input/dropdown/DropdownSearchInput.svelte';

  let {
    oncomplete,
    oncancel,
    onfocusreturn,
    initialType,
  }: {
    oncomplete: (linkText: string) => void;
    oncancel: () => void;
    onfocusreturn?: () => void;
    /** When set, skip the type picker and jump directly to this link type. */
    initialType?: string;
  } = $props();

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  let stage = $state<'type' | 'search' | 'cite'>(
    untrack(() => (initialType === 'cite' ? 'cite' : 'type')),
  );

  // Type picker
  let linkTypes = $state<LinkType[]>([]);
  let typeIndex = $state(0);

  // Search
  let selectedType = $state<LinkType | null>(null);
  let searchQuery = $state('');
  let searchResults = $state<LinkTarget[]>([]);
  let searchIndex = $state(-1);
  let searchInputEl: HTMLInputElement | undefined = $state();
  let debouncedSearch: ReturnType<typeof createDebouncedSearch<LinkTarget[]>> | null = null;

  // ARIA — per-instance IDs for combobox pattern
  const uid = Math.random().toString(36).slice(2, 8);
  const listboxId = `wl-results-${uid}`;
  function resultItemId(ref: string) {
    return `wl-result-${uid}-${ref}`;
  }
  let activeDescendant = $derived(
    searchIndex >= 0 && searchIndex < searchResults.length
      ? resultItemId(searchResults[searchIndex].ref)
      : undefined,
  );

  onDestroy(() => debouncedSearch?.cancel());

  $effect(() => {
    if (stage === 'search' && searchInputEl) {
      searchInputEl.focus();
    }
  });

  $effect(() => {
    if (stage !== 'search' || searchIndex < 0) return;
    const el = searchInputEl?.closest('.wikilink-autocomplete');
    el?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  });

  // Eagerly prefetch link types so they're ready before the user types [[.
  // Cached at module level, so this is a no-op after first call.
  fetchLinkTypes()
    .then((types) => {
      linkTypes = types;
    })
    .catch(() => {
      // Degraded state: type picker will be empty
    });

  // Honor initialType both at mount and when it changes after mount (e.g.
  // user typed `[[` to open the type picker, then clicked the Citation
  // toolbar button — the parent updates `initialType` on the already-mounted
  // component, so we react here to advance past the type picker).
  $effect(() => {
    if (!initialType || stage !== 'type' || linkTypes.length === 0) return;
    const match = linkTypes.find((t) => t.name === initialType);
    if (match) selectType(match);
  });

  // -----------------------------------------------------------------------
  // Type picker stage
  // -----------------------------------------------------------------------

  function selectType(lt: LinkType) {
    selectedType = lt;
    if (lt.flow === 'custom' && lt.name === 'cite') {
      stage = 'cite';
    } else {
      searchQuery = '';
      searchResults = [];
      searchIndex = -1;
      // Create a fresh debounced search bound to this type
      debouncedSearch = createDebouncedSearch<LinkTarget[]>(
        async (q: string) => {
          try {
            const response = await searchLinkTargets(lt.name, q);
            return response.results;
          } catch {
            return [];
          }
        },
        (results) => {
          searchResults = results;
        },
      );
      stage = 'search';
      debouncedSearch.search('');
    }
  }

  // -----------------------------------------------------------------------
  // Search stage
  // -----------------------------------------------------------------------

  function handleSearchInput(e: Event) {
    searchQuery = (e.currentTarget as HTMLInputElement).value;
    searchIndex = -1;
    debouncedSearch?.search(searchQuery);
  }

  function selectResult(target: LinkTarget) {
    if (!selectedType) return;
    oncomplete(formatLinkText(selectedType.name, target.ref));
  }

  function goBack() {
    if (initialType) {
      // Arrived via toolbar — no type picker to go back to, just close
      oncancel();
      return;
    }
    debouncedSearch?.cancel();
    debouncedSearch = null;
    stage = 'type';
    selectedType = null;
    searchQuery = '';
    searchResults = [];
    searchIndex = -1;
    // Preserve typeIndex so the user returns to the type they selected
    onfocusreturn?.();
  }

  // -----------------------------------------------------------------------
  // Keyboard navigation
  // -----------------------------------------------------------------------

  function handleTypeKeydown(e: KeyboardEvent) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        typeIndex = Math.min(typeIndex + 1, linkTypes.length - 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        typeIndex = Math.max(typeIndex - 1, 0);
        break;
      case 'Enter':
      case 'ArrowRight':
        e.preventDefault();
        if (typeIndex >= 0 && typeIndex < linkTypes.length) {
          selectType(linkTypes[typeIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        oncancel();
        break;
      case 'Backspace':
      case 'ArrowLeft':
        // Browser will delete a [ / move cursor — close since trigger is being left
        oncancel();
        break;
    }
  }

  function handleSearchKeydown(e: KeyboardEvent) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        searchIndex = Math.min(searchIndex + 1, searchResults.length - 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        searchIndex = Math.max(searchIndex - 1, -1);
        break;
      case 'Enter':
        e.preventDefault();
        if (searchIndex >= 0 && searchIndex < searchResults.length) {
          selectResult(searchResults[searchIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        debouncedSearch?.cancel();
        oncancel();
        break;
      case 'Backspace':
        if (!searchQuery) {
          e.preventDefault();
          goBack();
        }
        break;
      case 'ArrowLeft':
        if (searchInputEl && searchInputEl.selectionStart === 0) {
          e.preventDefault();
          goBack();
        }
        break;
    }
  }

  // -----------------------------------------------------------------------
  // Public: let parent forward keydown events from the textarea
  // -----------------------------------------------------------------------

  export function handleExternalKeydown(e: KeyboardEvent) {
    if (stage === 'type') {
      handleTypeKeydown(e);
    }
  }
</script>

<div class="wikilink-autocomplete">
  {#if stage === 'type'}
    <DropdownHeader>Insert link</DropdownHeader>
    {#each linkTypes as lt, i (lt.name)}
      <DropdownItem
        active={i === typeIndex}
        onselect={() => selectType(lt)}
        onhover={() => (typeIndex = i)}
      >
        <span class="item-label">{lt.label}</span>
        <span class="item-desc">{lt.description}</span>
      </DropdownItem>
    {/each}
  {:else if stage === 'search'}
    <DropdownHeader onback={goBack}>{selectedType?.label}</DropdownHeader>
    <DropdownSearchInput
      placeholder="Search {selectedType?.label ?? ''}..."
      value={searchQuery}
      oninput={handleSearchInput}
      onkeydown={handleSearchKeydown}
      bind:inputRef={searchInputEl}
      {activeDescendant}
      {listboxId}
    />
    <div class="results-list" role="listbox" id={listboxId}>
      {#each searchResults as target, i (target.ref)}
        <DropdownItem
          id={resultItemId(target.ref)}
          active={i === searchIndex}
          onselect={() => selectResult(target)}
          onhover={() => (searchIndex = i)}
        >
          <span class="item-label">{target.label}</span>
        </DropdownItem>
      {:else}
        <div class="no-results">No matches</div>
      {/each}
    </div>
  {:else if stage === 'cite'}
    <CitationAutocomplete
      oncomplete={(instance) => oncomplete(`[[cite:${instance.slug}]]`)}
      oncancel={() => oncancel()}
      onback={() => goBack()}
    />
  {/if}
</div>

<style>
  .item-label {
    flex-shrink: 0;
  }

  .item-desc {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .results-list {
    max-height: 14rem;
    overflow-y: auto;
  }

  .no-results {
    padding: var(--size-3);
    color: var(--color-text-muted);
    text-align: center;
    font-size: var(--font-size-1);
  }
</style>
