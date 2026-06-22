<script lang="ts">
  import client from '$lib/api/client';
  import { createDebouncedSearch } from '$lib/components/input/dropdown/search-helpers';
  import {
    createChildByIdentifier,
    type ParentContext,
    type ChildSource,
    type CreateSeed,
  } from './citation-types';
  import DropdownHeader from '$lib/components/input/dropdown/DropdownHeader.svelte';
  import DropdownItem from '$lib/components/input/dropdown/DropdownItem.svelte';
  import DropdownSearchInput from '$lib/components/input/dropdown/DropdownSearchInput.svelte';

  let {
    parentContext,
    onsourceidentified,
    oncreatestarted,
    oncancel,
    onback,
  }: {
    parentContext: ParentContext;
    onsourceidentified: (child: {
      sourceId: number;
      sourceName: string;
      skipLocator: boolean;
    }) => void;
    oncreatestarted: (seed: CreateSeed) => void;
    oncancel: () => void;
    onback: () => void;
  } = $props();

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  let filterQuery = $state('');
  let children = $state<ChildSource[]>([]);
  let allChildren = $state<ChildSource[]>([]);
  let loading = $state(true);
  let loadError = $state(false);
  let activeIndex = $state(-1);
  let searchInputEl: HTMLInputElement | undefined = $state();
  let resultsListEl: HTMLDivElement | undefined = $state();
  let creatingIdentifier = $state(false);
  let createError = $state('');

  let isWeb = $derived(parentContext.source_type === 'web');
  let placeholder = $derived(isWeb ? 'Search pages...' : 'Filter editions...');
  let emptyMessage = $derived(
    isWeb ? 'No pages yet — type to create one' : 'No editions yet — type to create one',
  );

  // For parents with identifier_key, the filter input doubles as identifier
  // entry. When the input doesn't match any existing children, offer a
  // direct "Create Citation" that posts with the identifier.
  let canQuickCreate = $derived(
    !loading &&
      !loadError &&
      filterQuery.trim().length > 0 &&
      children.length === 0 &&
      !!parentContext.identifier_key,
  );

  // ARIA — per-instance IDs for combobox pattern
  const uid = Math.random().toString(36).slice(2, 8);
  const listboxId = `cite-identify-${uid}`;
  function itemId(key: string | number) {
    return `cite-identify-item-${uid}-${key}`;
  }

  // -----------------------------------------------------------------------
  // Fetch all children on mount (for initial display)
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

  $effect(() => {
    fetchChildren();
  });

  async function fetchChildren() {
    loading = true;
    loadError = false;
    const { data, error } = await client.GET('/api/citation-sources/{source_id}/', {
      params: { path: { source_id: parentContext.id } },
    });
    if (error || !data) {
      loading = false;
      loadError = true;
      return;
    }
    // Sort newest-first by year (nulls at end)
    allChildren = [...(data.children as ChildSource[])].sort((a, b) => {
      if (a.year == null && b.year == null) return 0;
      if (a.year == null) return 1;
      if (b.year == null) return -1;
      return b.year - a.year;
    });
    children = allChildren;
    loading = false;
  }

  // -----------------------------------------------------------------------
  // Debounced server-side child search
  // -----------------------------------------------------------------------

  const debouncedChildSearch = createDebouncedSearch<ChildSource[]>(
    async (q: string) => {
      if (!q.trim()) return allChildren;
      const { data } = await client.GET('/api/citation-sources/{source_id}/children/', {
        params: { path: { source_id: parentContext.id }, query: { q } },
      });
      return (data as ChildSource[] | undefined) ?? [];
    },
    (results) => {
      children = results;
    },
    150,
  );

  // -----------------------------------------------------------------------
  // Item index math
  // -----------------------------------------------------------------------

  let showCreateNew = $derived(
    !loading && !loadError && filterQuery.trim().length > 0 && (!canQuickCreate || createError),
  );
  let quickCreateIndex = $derived(children.length);
  let createNewIndex = $derived(children.length + (canQuickCreate ? 1 : 0));
  let totalItems = $derived(
    loading || loadError ? 0 : children.length + (canQuickCreate ? 1 : 0) + (showCreateNew ? 1 : 0),
  );
  let activeDescendant = $derived(
    activeIndex >= 0 && activeIndex < totalItems
      ? itemId(children[activeIndex]?.id ?? `create-${createNewIndex}`)
      : undefined,
  );

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  function selectChild(child: ChildSource) {
    debouncedChildSearch.cancel();
    onsourceidentified({
      sourceId: child.id,
      sourceName: child.name,
      skipLocator: child.skip_locator,
    });
  }

  function startCreate() {
    debouncedChildSearch.cancel();
    if (isWeb) {
      // A page under a known web root: hand off to the web flow's page step
      // (Create Site skipped — the site exists). The typed text prefills the
      // page name; the URL is entered there. One web-create path, via cite-url.
      oncreatestarted({
        kind: 'web',
        url: '',
        siteName: parentContext.name,
        draft: null,
        pageName: filterQuery.trim(),
      });
      return;
    }
    oncreatestarted({ kind: 'name', name: filterQuery.trim() });
  }

  async function quickCreateByIdentifier() {
    if (creatingIdentifier || !filterQuery.trim()) return;
    debouncedChildSearch.cancel();
    creatingIdentifier = true;
    createError = '';
    const result = await createChildByIdentifier(
      client,
      parentContext.id,
      parentContext.name,
      parentContext.source_type,
      filterQuery.trim(),
    );
    if (!result.ok) {
      creatingIdentifier = false;
      createError = result.error;
      return;
    }
    onsourceidentified({
      sourceId: result.sourceId,
      sourceName: result.sourceName,
      skipLocator: result.skipLocator,
    });
  }

  // -----------------------------------------------------------------------
  // Input handling
  // -----------------------------------------------------------------------

  function handleSearchInput(e: Event) {
    filterQuery = (e.currentTarget as HTMLInputElement).value;
    activeIndex = -1;
    createError = '';
    creatingIdentifier = false;
    debouncedChildSearch.search(filterQuery);
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
        if (activeIndex < children.length) {
          selectChild(children[activeIndex]);
        } else if (canQuickCreate && activeIndex === quickCreateIndex) {
          quickCreateByIdentifier();
        } else if (showCreateNew && activeIndex === createNewIndex) {
          startCreate();
        }
        break;
      case 'Escape':
        e.preventDefault();
        oncancel();
        break;
      case 'Backspace':
        if (!filterQuery) {
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

<DropdownHeader {onback}>{parentContext.name}</DropdownHeader>
<DropdownSearchInput
  {placeholder}
  value={filterQuery}
  oninput={handleSearchInput}
  onkeydown={handleKeydown}
  bind:inputRef={searchInputEl}
  {activeDescendant}
  {listboxId}
/>
<div class="results-list" role="listbox" id={listboxId} bind:this={resultsListEl}>
  {#if loading}
    <div class="status-msg">Loading…</div>
  {:else if loadError}
    <div class="status-msg status-error">
      {isWeb ? 'Failed to load pages.' : 'Failed to load editions.'}
    </div>
  {:else}
    {#each children as child, i (child.id)}
      <DropdownItem
        id={itemId(child.id)}
        active={i === activeIndex}
        onselect={() => selectChild(child)}
        onhover={() => (activeIndex = i)}
      >
        <span class="item-label">{child.name}{child.year != null ? ` — ${child.year}` : ''}</span>
      </DropdownItem>
    {/each}
    {#if canQuickCreate && !createError}
      <DropdownItem
        id={itemId(`quick-create-${quickCreateIndex}`)}
        active={activeIndex === quickCreateIndex}
        onselect={quickCreateByIdentifier}
        onhover={() => (activeIndex = quickCreateIndex)}
      >
        <span class="item-label">{parentContext.name} #{filterQuery.trim()}</span>
        <span class="item-desc">{creatingIdentifier ? 'Creating…' : 'Create Citation'}</span>
      </DropdownItem>
    {/if}
    {#if createError}
      <div class="status-msg status-error">{createError}</div>
    {/if}
    {#if showCreateNew}
      <DropdownItem
        id={itemId(`create-${createNewIndex}`)}
        active={activeIndex === createNewIndex}
        onselect={startCreate}
        onhover={() => (activeIndex = createNewIndex)}
      >
        <span class="item-label create-new">+ Create "{filterQuery}"</span>
      </DropdownItem>
    {/if}
    {#if !children.length && !filterQuery.trim()}
      <div class="status-msg">{emptyMessage}</div>
    {:else if !children.length && filterQuery.trim() && !canQuickCreate}
      <div class="status-msg">No matches</div>
    {/if}
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

  .results-list {
    max-height: 14rem;
    overflow-y: auto;
  }

  .status-msg {
    padding: var(--size-3);
    color: var(--color-text-muted);
    text-align: center;
    font-size: var(--font-size-1);
  }

  .status-error {
    color: var(--color-error-text);
  }
</style>
