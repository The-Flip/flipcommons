<script lang="ts">
  import client from '$lib/api/client';
  import {
    createDebouncedSearch,
    formatCitationResult,
  } from '$lib/components/input/dropdown/search-helpers';
  import {
    suppressChildResults,
    createChildByIdentifier,
    urlFromQuery,
    isbnFromQuery,
    type CitationSourceResult,
    type RecognitionResult,
    type CreateSeed,
    type ExtractionDraft,
  } from './citation-types';
  import type {
    CitationExtractDelivererSchema,
    CitationSourceSearchResponseSchema,
  } from '$lib/api/schema';
  import DropdownButton from '$lib/components/input/dropdown/DropdownButton.svelte';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import DropdownItem from '$lib/components/input/dropdown/DropdownItem.svelte';
  import DropdownSearchInput from '$lib/components/input/dropdown/DropdownSearchInput.svelte';

  let {
    onsourceselected,
    onsourceidentified,
    oncreatestarted,
    oncancel,
    onback,
  }: {
    onsourceselected: (source: CitationSourceResult) => void;
    onsourceidentified: (child: {
      sourceId: number;
      sourceName: string;
      sourceType: string;
      skipLocator: boolean;
      locatorHint?: string;
    }) => void;
    oncreatestarted: (seed: CreateSeed) => void;
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
  /** The deliverer teaching notice: the pasted URL is a store/streaming copy
   *  of a work, so web-create is never offered — the CTA hands off to the
   *  authored-work form instead. `url` rides along so the handoff seed can
   *  carry the pasted string through flow state (the access-URL hedge). */
  let delivererNotice = $state<{
    notice: CitationExtractDelivererSchema;
    url: string;
  } | null>(null);

  // -----------------------------------------------------------------------
  // ISBN detection — whole input or embedded in pasted text (isbnFromQuery)
  // -----------------------------------------------------------------------

  let isbnInput = $derived(
    !recognition && searchResults.length === 0 && searchQuery.trim()
      ? isbnFromQuery(searchQuery)
      : null,
  );

  // -----------------------------------------------------------------------
  // URL detection
  // -----------------------------------------------------------------------

  // Accepts scheme-less hosts too (`www.imdb.com/…` → `https://www.imdb.com/…`),
  // so a pasted URL without http(s):// still routes through the URL flow rather
  // than falling to "+ Create". The lookup/create then sees a valid URL.
  let urlInput = $derived(
    !recognition && searchResults.length === 0 ? urlFromQuery(searchQuery) : null,
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
    delivererNotice = null;
    // Send the normalized URL (scheme prepended) so the backend recognizes a
    // scheme-less host the same as a schemed one — otherwise a domain match is
    // missed and the URL wrongly creates a new root instead of a child.
    debouncedSearch.search(urlFromQuery(searchQuery) ?? searchQuery);
  }

  // -----------------------------------------------------------------------
  // Recognition-derived items
  // -----------------------------------------------------------------------

  // Recognition can produce a top item: exact child match, or identifier-based quick create
  let recognitionItem = $derived.by(() => {
    if (!recognition) return null;
    if (recognition.child) {
      return {
        type: 'exact_match' as const,
        label: recognition.child.name,
        id: recognition.child.id,
        sourceType: recognition.child.source_type,
        skipLocator: recognition.child.skip_locator,
        locatorHint: recognition.locator_hint,
      };
    }
    if (recognition.identifier) {
      return {
        type: 'create_identified' as const,
        label: `${recognition.parent.name} #${recognition.identifier}`,
        parentId: recognition.parent.id,
        identifier: recognition.identifier,
        locatorHint: recognition.locator_hint,
      };
    }
    // Domain-only match — the site is known but this page isn't a child yet.
    // Selecting it hands off to the web flow's page step. `url` is the
    // normalized form so a scheme-less paste carries a valid URL (the displayed
    // `label` stays as the user typed it).
    return {
      type: 'create_by_url' as const,
      label: searchQuery.trim(),
      url: urlFromQuery(searchQuery) ?? searchQuery.trim(),
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
  // A URL has its own "Use this URL →" action that always advances to the create
  // stage, so the generic "+ Create" would be a redundant, worse path (it leaves
  // the raw URL as the name and defaults to book). Suppress it for URL input.
  let showCreateNew = $derived(searchQuery.trim().length > 0 && !recognition && !urlInput);
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
      // The exact page already exists — cite it directly, no create step.
      onsourceidentified({
        sourceId: recognitionItem.id,
        sourceName: recognitionItem.label,
        sourceType: recognitionItem.sourceType,
        skipLocator: recognitionItem.skipLocator,
        locatorHint: recognitionItem.locatorHint,
      });
      return;
    }

    if (recognitionItem.type === 'create_by_url') {
      // The site is recognized but this exact page isn't a child yet. Scrape the
      // page for its metadata, then hand off to the web flow's page step (Create
      // Site is skipped — the site exists); it writes only on finalize.
      startWebCite(recognitionItem.url, recognitionItem.parentName);
      return;
    }

    // create_identified (a scheme child, e.g. IPDB): one-click child create.
    if (creating) return;
    creating = true;
    createError = '';

    const result = await createChildByIdentifier(
      client,
      recognitionItem.parentId,
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
      sourceType: result.sourceType,
      skipLocator: result.skipLocator,
      // The pasted URL's start time (?t=95) rides the recognition response;
      // the newly minted child inherits it as the locator prefill.
      locatorHint: recognitionItem.locatorHint,
    });
  }

  function startCreate() {
    debouncedSearch.cancel();
    oncreatestarted({ kind: 'name', name: searchQuery.trim() });
  }

  /** Scrape an ISBN or URL via the extract endpoint, then route the result:
   *  an existing match cites directly; a draft or a recoverable failure is
   *  handed to `onDraft` (which builds the seed); an unrecoverable failure with
   *  no `onFailure` shows a message. */
  async function lookupExtraction(
    input: string,
    {
      errorMessages = {},
      onDraft,
      onDeliverer = null,
      onFailure = null,
    }: {
      errorMessages?: Record<string, string>;
      onDraft: (draft: ExtractionDraft) => void;
      onDeliverer?: ((notice: CitationExtractDelivererSchema) => void) | null;
      onFailure?: ((errorCode: string | null) => void) | null;
    },
  ) {
    if (extracting) return;
    extracting = true;
    extractError = '';

    const { data, error } = await client.POST('/api/citation-sources/extract/', {
      body: { input },
    });

    extracting = false;

    if (!error && data?.match) {
      debouncedSearch.cancel();
      onsourceidentified({
        sourceId: data.match.id,
        sourceName: data.match.name,
        sourceType: data.match.source_type,
        skipLocator: data.match.skip_locator,
      });
      return;
    }

    if (!error && data?.deliverer && onDeliverer) {
      // A deliverer verdict: the URL is a store/streaming copy of a work, so
      // web-create must never be offered. Stay on this stage and teach.
      onDeliverer(data.deliverer);
      return;
    }

    if (!error && data?.draft) {
      debouncedSearch.cancel();
      onDraft(data.draft);
      return;
    }

    // No match and no draft: the lookup failed. Distinguish a returned error
    // code (data.error) from a transport failure (no data) so the caller can
    // treat them differently — the URL path advances on a recoverable failure
    // but dead-ends a `blocked` host.
    const code = error || !data ? null : (data.error ?? null);
    if (onFailure) {
      debouncedSearch.cancel();
      onFailure(code);
      return;
    }
    const fallbackMsg = 'Lookup failed. You can still create manually.';
    extractError = code === null ? fallbackMsg : (errorMessages[code] ?? fallbackMsg);
  }

  function lookupIsbn(isbn: string) {
    lookupExtraction(isbn, {
      errorMessages: {
        not_found: 'ISBN not found. You can still create manually.',
        timeout: 'Lookup timed out. You can still create manually.',
        api_error: 'External service error. You can still create manually.',
      },
      onDraft: (draft) => oncreatestarted({ kind: 'extraction', draft }),
    });
  }

  /** Scrape a web URL, then route by the backend's verdict: a web draft enters
   *  the web create flow; a book draft (a deliverer URL whose ISBN resolved)
   *  belongs in the authored-work form, prefilled — same as an ISBN paste; a
   *  deliverer notice stays here and teaches. `siteName` is the recognized site
   *  (existing — Create Site is skipped) or null (a new site). A successful web
   *  scrape prefills the page (and, for a new site, the site name); a
   *  recoverable failure advances with nothing prefilled. A `blocked` host (SSRF
   *  guard: internal/private address) must NOT become a citation — dead-end it. */
  function startWebCite(url: string, siteName: string | null) {
    lookupExtraction(url, {
      onDraft: (draft) => {
        if (draft.source_type === 'web') {
          oncreatestarted({ kind: 'web', url, siteName, draft });
        } else {
          oncreatestarted({ kind: 'extraction', draft });
        }
      },
      onDeliverer: (notice) => {
        delivererNotice = { notice, url };
      },
      onFailure: (code) => {
        if (code === 'blocked') {
          extractError = "That URL can't be cited — it points to a disallowed or internal address.";
          return;
        }
        oncreatestarted({ kind: 'web', url, siteName, draft: null });
      },
    });
  }

  /** The deliverer CTA: hand off to the authored-work form with the suggested
   *  type preselected, carrying the pasted URL through the seed (unused today
   *  — the access-URL hedge). */
  function startDelivererCreate() {
    if (!delivererNotice) return;
    debouncedSearch.cancel();
    oncreatestarted({
      kind: 'name',
      name: '',
      sourceType: delivererNotice.notice.suggested_source_type ?? undefined,
      url: delivererNotice.url,
    });
  }

  function lookupUrl(url: string) {
    startWebCite(url, null);
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
      {#if recognitionItem.type === 'create_by_url'}
        <div class="recognition-parent">
          Cite a page under <strong>{recognitionItem.parentName}</strong>
        </div>
      {/if}
      <!-- Wrapper aligns the button to the start of the flex column (the button
           shouldn't stretch full width). align-self can't live on the child
           component's element from here, so it goes on this wrapper. -->
      <div class="recognition-action">
        <DropdownButton
          disabled={creating || extracting}
          onpointerdown={(e) => {
            e.preventDefault();
            handleRecognitionSelect();
          }}
        >
          {#if recognitionItem.type === 'exact_match'}
            Cite
          {:else if recognitionItem.type === 'create_by_url'}
            {extracting ? 'Looking up…' : 'Continue'}
          {:else if creating}
            Creating…
          {:else}
            Continue
          {/if}
        </DropdownButton>
      </div>
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
        <span class="item-label">Use this URL →</span>
      {/if}
    </DropdownItem>
  {/if}
  {#if delivererNotice}
    <!-- The teaching moment: a deliverer URL never advances to web-create.
         The CTA is the only forward action; searching stays available. -->
    <div class="deliverer-notice">
      <div class="deliverer-message">{delivererNotice.notice.message}</div>
      <div class="recognition-action">
        <DropdownButton
          onpointerdown={(e) => {
            e.preventDefault();
            startDelivererCreate();
          }}
        >
          {delivererNotice.notice.suggested_source_type
            ? `Cite the ${delivererNotice.notice.suggested_source_type} instead`
            : 'Cite the work instead'}
        </DropdownButton>
      </div>
    </div>
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

  .recognition-action {
    align-self: flex-start;
  }

  .recognition-label {
    font-size: var(--font-size-1);
  }

  .recognition-parent {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .create-error {
    padding: var(--size-2) var(--size-3);
    color: var(--color-error-text);
    font-size: var(--font-size-0);
    text-align: center;
  }

  .deliverer-notice {
    padding: var(--size-2) var(--size-3);
    display: flex;
    flex-direction: column;
    gap: var(--size-2);
  }

  .deliverer-message {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .no-results {
    padding: var(--size-3);
    color: var(--color-text-muted);
    text-align: center;
    font-size: var(--font-size-1);
  }
</style>
