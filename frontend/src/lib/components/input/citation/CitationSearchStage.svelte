<script lang="ts">
  import client from '$lib/api/client';
  import {
    createDebouncedSearch,
    formatCitationResult,
  } from '$lib/components/input/dropdown/search-helpers';
  import {
    suppressChildResults,
    createChildByIdentifier,
    type CitationSourceResult,
    type RecognitionResult,
    type ExtractionDraft,
  } from './citation-types';
  import type { CitationSourceSearchResponseSchema } from '$lib/api/schema';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import DropdownItem from '$lib/components/input/dropdown/DropdownItem.svelte';
  import DropdownSearchInput from '$lib/components/input/dropdown/DropdownSearchInput.svelte';

  let {
    onsourceselected,
    onsourceidentified,
    onsourcecreatestarted,
    onextractiondraft,
    oncancel,
    onback,
  }: {
    onsourceselected: (source: CitationSourceResult) => void;
    onsourceidentified: (child: {
      sourceId: number;
      sourceName: string;
      skipLocator: boolean;
    }) => void;
    onsourcecreatestarted: (prefillName: string) => void;
    onextractiondraft: (draft: ExtractionDraft) => void;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  let searchQuery = $state('');
  let searchResults = $state<CitationSourceResult[]>([]);
  let recognition = $state<RecognitionResult | null>(null);
  let activeIndex = $state(-1);
  let searchInputEl: HTMLInputElement | undefined = $state();
  let resultsListEl: HTMLDivElement | undefined = $state();
  let creating = $state(false);
  let createError = $state('');
  let extracting = $state(false);
  let extractError = $state('');

  // -----------------------------------------------------------------------
  // ISBN detection
  // -----------------------------------------------------------------------

  function normalizeIsbn(raw: string): string | null {
    const stripped = raw.replace(/-/g, '').replace(/ /g, '').toUpperCase();
    if (stripped.length === 13 && /^\d{13}$/.test(stripped)) return stripped;
    if (stripped.length === 10 && /^\d{9}[\dX]$/.test(stripped)) return stripped;
    return null;
  }

  let isbnInput = $derived(
    !recognition && searchResults.length === 0 && searchQuery.trim()
      ? normalizeIsbn(searchQuery)
      : null,
  );

  // -----------------------------------------------------------------------
  // URL detection
  // -----------------------------------------------------------------------

  let urlInput = $derived(
    !recognition &&
      searchResults.length === 0 &&
      searchQuery.trim() &&
      (searchQuery.trim().startsWith('http://') || searchQuery.trim().startsWith('https://'))
      ? searchQuery.trim()
      : null,
  );

  // ARIA — per-instance IDs for combobox pattern
  const uid = Math.random().toString(36).slice(2, 8);
  const listboxId = `cite-search-${uid}`;
  function itemId(key: string | number) {
    return `cite-search-item-${uid}-${key}`;
  }

  // -----------------------------------------------------------------------
  // Debounced search (backend handles recognition)
  // -----------------------------------------------------------------------

  const emptyResponse: CitationSourceSearchResponseSchema = { results: [], recognition: null };

  const debouncedSearch = createDebouncedSearch<CitationSourceSearchResponseSchema>(
    async (q: string) => {
      if (!q.trim()) return emptyResponse;
      const { data } = await client.GET('/api/citation-sources/search/', {
        params: { query: { q } },
      });
      return (data as CitationSourceSearchResponseSchema | undefined) ?? emptyResponse;
    },
    (response) => {
      recognition = response.recognition ?? null;
      const recognizedChildId = recognition?.child?.id;
      const filtered = recognizedChildId
        ? response.results.filter((r) => r.id !== recognizedChildId)
        : response.results;
      searchResults = suppressChildResults(filtered);
    },
    100,
  );

  function handleSearchInput(e: Event) {
    searchQuery = (e.currentTarget as HTMLInputElement).value;
    activeIndex = -1;
    creating = false;
    createError = '';
    extractError = '';
    debouncedSearch.search(searchQuery);
  }

  // -----------------------------------------------------------------------
  // Recognition-derived items
  // -----------------------------------------------------------------------

  // Recognition can produce a top item: exact child match, or identifier-based "Create & cite"
  let recognitionItem = $derived.by(() => {
    if (!recognition) return null;
    if (recognition.child) {
      return {
        type: 'exact_match' as const,
        label: recognition.child.name,
        id: recognition.child.id,
        skipLocator: recognition.child.skip_locator,
      };
    }
    if (recognition.identifier) {
      return {
        type: 'create_identified' as const,
        label: `${recognition.parent.name} #${recognition.identifier}`,
        parentId: recognition.parent.id,
        identifier: recognition.identifier,
      };
    }
    // Domain-only match — create child with the pasted URL
    return {
      type: 'create_by_url' as const,
      label: searchQuery.trim(),
      parentId: recognition.parent.id,
      parentName: recognition.parent.name,
    };
  });

  // -----------------------------------------------------------------------
  // Item index math
  // -----------------------------------------------------------------------

  let hasRecognitionItem = $derived(recognitionItem !== null);
  let hasIsbnItem = $derived(isbnInput !== null && !recognition);
  let hasUrlItem = $derived(urlInput !== null && !recognition);
  let hasExtractionItem = $derived(hasIsbnItem || hasUrlItem);
  let showCreateNew = $derived(searchQuery.trim().length > 0 && !recognition);
  let resultsStartIndex = $derived(hasRecognitionItem ? 1 : hasExtractionItem ? 1 : 0);
  let createNewIndex = $derived(resultsStartIndex + searchResults.length);
  let totalItems = $derived(
    (hasRecognitionItem ? 1 : hasExtractionItem ? 1 : 0) +
      searchResults.length +
      (showCreateNew ? 1 : 0),
  );
  let activeDescendant = $derived.by(() => {
    if (activeIndex < 0 || activeIndex >= totalItems) return undefined;
    if (hasRecognitionItem && activeIndex === 0) return itemId('recognition');
    if (hasIsbnItem && activeIndex === 0) return itemId('isbn');
    if (hasUrlItem && activeIndex === 0) return itemId('url');
    if (activeIndex >= resultsStartIndex && activeIndex < createNewIndex)
      return itemId(searchResults[activeIndex - resultsStartIndex].id);
    if (activeIndex === createNewIndex) return itemId('create');
    return undefined;
  });

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  $effect(() => {
    if (searchInputEl) {
      searchInputEl.focus();
    }
  });

  $effect(() => {
    if (activeIndex < 0 || !resultsListEl) return;
    resultsListEl.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  });

  function selectSource(source: CitationSourceResult) {
    debouncedSearch.cancel();
    onsourceselected(source);
  }

  async function handleRecognitionSelect() {
    if (!recognitionItem) return;
    debouncedSearch.cancel();

    if (recognitionItem.type === 'exact_match') {
      onsourceidentified({
        sourceId: recognitionItem.id,
        sourceName: recognitionItem.label,
        skipLocator: recognitionItem.skipLocator,
      });
      return;
    }

    if (creating) return;
    creating = true;
    createError = '';

    if (recognitionItem.type === 'create_identified') {
      const result = await createChildByIdentifier(
        client,
        recognitionItem.parentId,
        recognition!.parent.name,
        'web',
        recognitionItem.identifier,
      );
      if (!result.ok) {
        creating = false;
        createError = result.error;
        return;
      }
      onsourceidentified({
        sourceId: result.sourceId,
        sourceName: result.sourceName,
        skipLocator: result.skipLocator,
      });
      return;
    }

    // create_by_url: mint a child under the domain-matched parent. Its link is
    // 'reference' (not 'homepage') — an article page is evidence, and a homepage
    // link would let it pose as a domain root in later URL recognition.
    const { data, error } = await client.POST('/api/citation-sources/', {
      body: {
        name: recognitionItem.label,
        source_type: 'web',
        author: '',
        publisher: '',
        date_note: '',
        description: '',
        parent_id: recognitionItem.parentId,
        identifier: '',
        url: recognitionItem.label,
        link_label: '',
        link_type: 'reference',
      },
    });
    if (error) {
      creating = false;
      createError = typeof error === 'string' ? error : 'Failed to create source.';
      return;
    }
    onsourceidentified({
      sourceId: data.id,
      sourceName: data.name,
      skipLocator: data.skip_locator,
    });
  }

  function startCreate() {
    debouncedSearch.cancel();
    onsourcecreatestarted(searchQuery);
  }

  async function lookupExtraction(input: string, errorMessages: Record<string, string>) {
    if (extracting) return;
    extracting = true;
    extractError = '';

    const { data, error } = await client.POST('/api/citation-sources/extract/', {
      body: { input },
    });

    extracting = false;

    if (error || !data) {
      extractError = 'Lookup failed. You can still create manually.';
      return;
    }

    if (data.match) {
      debouncedSearch.cancel();
      onsourceidentified({
        sourceId: data.match.id,
        sourceName: data.match.name,
        skipLocator: data.match.skip_locator,
      });
      return;
    }

    if (data.draft) {
      debouncedSearch.cancel();
      onextractiondraft(data.draft);
      return;
    }

    extractError =
      errorMessages[data.error ?? ''] ?? 'Lookup failed. You can still create manually.';
  }

  function lookupIsbn(isbn: string) {
    lookupExtraction(isbn, {
      not_found: 'ISBN not found. You can still create manually.',
      timeout: 'Lookup timed out. You can still create manually.',
      api_error: 'External service error. You can still create manually.',
    });
  }

  function lookupUrl(url: string) {
    lookupExtraction(url, {
      not_found: 'Page not found. You can still create manually.',
      blocked: 'URL not allowed. You can still create manually.',
      timeout: 'Lookup timed out. You can still create manually.',
      api_error: 'External service error. You can still create manually.',
    });
  }

  // -----------------------------------------------------------------------
  // Keyboard navigation
  // -----------------------------------------------------------------------

  function handleKeydown(e: KeyboardEvent) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, totalItems - 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, -1);
        break;
      case 'Enter':
        e.preventDefault();
        if (activeIndex < 0) break;
        if (hasRecognitionItem && activeIndex === 0) {
          handleRecognitionSelect();
        } else if (hasIsbnItem && activeIndex === 0) {
          if (isbnInput) lookupIsbn(isbnInput);
        } else if (hasUrlItem && activeIndex === 0) {
          if (urlInput) lookupUrl(urlInput);
        } else if (activeIndex >= resultsStartIndex && activeIndex < createNewIndex) {
          selectSource(searchResults[activeIndex - resultsStartIndex]);
        } else if (showCreateNew && activeIndex === createNewIndex) {
          startCreate();
        }
        break;
      case 'Escape':
        e.preventDefault();
        oncancel();
        break;
      case 'Backspace':
        if (!searchQuery) {
          e.preventDefault();
          onback();
        }
        break;
      case 'ArrowLeft':
        if (searchInputEl && searchInputEl.selectionStart === 0) {
          e.preventDefault();
          onback();
        }
        break;
    }
  }
</script>

<DropdownHeader {onback}>Citation</DropdownHeader>
<DropdownSearchInput
  placeholder="Search sources..."
  value={searchQuery}
  oninput={handleSearchInput}
  onkeydown={handleKeydown}
  bind:inputRef={searchInputEl}
  {activeDescendant}
  {listboxId}
/>
<div class="results-list" role="listbox" id={listboxId} bind:this={resultsListEl}>
  {#if recognitionItem}
    <div class="recognition-block" id={itemId('recognition')}>
      <div class="recognition-label">{recognitionItem.label}</div>
      <button
        class="recognition-btn"
        disabled={creating}
        onpointerdown={(e) => {
          e.preventDefault();
          handleRecognitionSelect();
        }}
      >
        {#if recognitionItem.type === 'exact_match'}
          Cite
        {:else if creating}
          Creating…
        {:else}
          Create & cite
        {/if}
      </button>
    </div>
  {/if}
  {#if isbnInput && !recognition}
    <DropdownItem
      id={itemId('isbn')}
      active={activeIndex === 0}
      onselect={() => {
        if (isbnInput) lookupIsbn(isbnInput);
      }}
      onhover={() => (activeIndex = 0)}
    >
      {#if extracting}
        <span class="item-label extract-loading">Looking up ISBN…</span>
      {:else}
        <span class="item-label">Look up ISBN {isbnInput}</span>
      {/if}
    </DropdownItem>
  {:else if urlInput && !recognition}
    <DropdownItem
      id={itemId('url')}
      active={activeIndex === 0}
      onselect={() => {
        if (urlInput) lookupUrl(urlInput);
      }}
      onhover={() => (activeIndex = 0)}
    >
      {#if extracting}
        <span class="item-label extract-loading">Looking up URL…</span>
      {:else}
        <span class="item-label">Look up URL</span>
      {/if}
    </DropdownItem>
  {/if}
  {#if extractError}
    <div class="create-error">{extractError}</div>
  {/if}
  {#if createError}
    <div class="create-error">{createError}</div>
  {/if}
  {#each searchResults as source, i (source.id)}
    <DropdownItem
      id={itemId(source.id)}
      active={i + resultsStartIndex === activeIndex}
      onselect={() => selectSource(source)}
      onhover={() => (activeIndex = i + resultsStartIndex)}
    >
      <span class="item-label">{formatCitationResult(source)}</span>
      <span class="item-desc">{source.source_type}</span>
    </DropdownItem>
  {/each}
  {#if showCreateNew}
    <DropdownItem
      id={itemId('create')}
      active={activeIndex === createNewIndex}
      onselect={startCreate}
      onhover={() => (activeIndex = createNewIndex)}
    >
      <span class="item-label create-new">+ Create "{searchQuery}"</span>
    </DropdownItem>
  {/if}
  {#if !recognition && !searchResults.length && !searchQuery.trim()}
    <div class="no-results">Type to search sources…</div>
  {:else if !recognition && !searchResults.length && searchQuery.trim() && !isbnInput && !urlInput}
    <div class="no-results">No matches</div>
  {/if}
</div>

<style>
  .item-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .item-desc {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    flex-shrink: 0;
  }

  .create-new {
    color: var(--color-text-muted);
    font-style: italic;
  }

  .extract-loading {
    color: var(--color-text-muted);
    font-style: italic;
  }

  .results-list {
    max-height: 14rem;
    overflow-y: auto;
  }

  .recognition-block {
    padding: var(--size-2) var(--size-3);
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .recognition-label {
    font-size: var(--font-size-1);
  }

  .recognition-btn {
    padding: var(--size-1) var(--size-2);
    font-size: var(--font-size-1);
    font-family: inherit;
    border: 1px solid var(--color-input-border);
    border-radius: var(--radius-2);
    background-color: var(--color-input-focus-ring);
    color: var(--color-text);
    cursor: pointer;
    align-self: flex-start;
  }

  .recognition-btn:hover:not(:disabled) {
    border-color: var(--color-input-focus);
  }

  .recognition-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .create-error {
    padding: var(--size-2) var(--size-3);
    color: var(--color-error-text);
    font-size: var(--font-size-0);
    text-align: center;
  }

  .no-results {
    padding: var(--size-3);
    color: var(--color-text-muted);
    text-align: center;
    font-size: var(--font-size-1);
  }
</style>
