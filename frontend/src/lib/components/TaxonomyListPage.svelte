<script
  lang="ts"
  generics="T extends { slug: string; name: string; aliases?: string[]; title_count?: number }"
>
  import type { Snippet } from 'svelte';
  import Page from './Page.svelte';
  import PageHeader from './PageHeader.svelte';
  import SearchBox from './SearchBox.svelte';
  import StatusMessage from './StatusMessage.svelte';
  import NoResultsCreatePrompt from './NoResultsCreatePrompt.svelte';
  import EditSectionMenu from './EditSectionMenu.svelte';
  import type { EditSectionMenuItem } from './edit-section-menu';
  import { SEARCH_THRESHOLD } from './grid/search-threshold';
  import { auth } from '$lib/auth.svelte';
  import { normalizeText, resolveHref } from '$lib/utils';
  import { pageTitle } from '$lib/constants';
  import { CATALOG_META, type CatalogEntityKey } from '$lib/api/catalog-meta';

  interface Props {
    /** Catalog entity key. Title, basePath, singular/plural labels, and endpoint are derived from CATALOG_META. */
    catalogKey: CatalogEntityKey;
    subtitle?: string;
    items: T[];
    loading: boolean;
    error: string | null;
    headerSnippet?: Snippet;
    rowSnippet?: Snippet<[item: T]>;
    /**
     * Optional override for the list rendering. When provided, replaces
     * the default `<ul>` of rows with caller-rendered content — useful
     * for grouped/hierarchical layouts. The filtered, search-narrowed
     * item list is passed in. Header, search, filters, and empty states
     * remain handled by this component.
     */
    listSnippet?: Snippet<[items: T[]]>;
    /**
     * When true, the page renders create affordances (auth-gated) pointing
     * at `/{entity_type_plural}/new`:
     *  - below SEARCH_THRESHOLD: a "+ New {entity}" link in the header
     *  - at/above the threshold: a SearchBox + inline filter; zero-match
     *    renders NoResultsCreatePrompt with the typed query.
     */
    canCreate?: boolean;
    /** Optional filter UI rendered between the SearchBox and the list. */
    filters?: Snippet;
    /**
     * Optional pre-search filter. Applied before the name/alias match so
     * the empty-state and zero-results prompts compose with active
     * filters. Callers own the filter state and bind it through their
     * `filters` snippet.
     */
    filterFn?: (item: T) => boolean;
  }

  let {
    catalogKey,
    subtitle,
    items,
    loading,
    error,
    headerSnippet,
    rowSnippet,
    listSnippet,
    canCreate = false,
    filters,
    filterFn,
  }: Props = $props();

  let meta = $derived(CATALOG_META[catalogKey]);
  let title = $derived(meta.label_plural);
  let basePath = $derived(`/${meta.entity_type_plural}`);
  let entityLabel = $derived(meta.label_plural.toLowerCase());
  let singularLabel = $derived(meta.label.toLowerCase());
  let singularTitle = $derived(meta.label);
  let endpoint = $derived(`/api${basePath}/`);
  let createHref = $derived(canCreate ? `${basePath}/new` : undefined);

  let searchQuery = $state('');

  $effect(() => {
    void auth.load();
  });

  let showSearch = $derived(items.length >= SEARCH_THRESHOLD || searchQuery.trim() !== '');

  let scopedItems = $derived(filterFn ? items.filter(filterFn) : items);

  let filteredItems = $derived.by(() => {
    const q = normalizeText(searchQuery.trim());
    if (!q) return scopedItems;
    // Per RecordCreateDelete.md:115, aliases must count as results for the
    // duplicate-prevention gate — otherwise a search for an existing alias
    // would wrongly trigger NoResultsCreatePrompt.
    return scopedItems.filter((item) => {
      if (normalizeText(item.name).includes(q)) return true;
      return (item.aliases ?? []).some((alias) => normalizeText(alias).includes(q));
    });
  });

  let actionItems: EditSectionMenuItem[] = $derived(
    createHref
      ? [{ key: 'new', label: `+ New ${singularTitle}`, href: resolveHref(createHref) }]
      : [],
  );

  let showActionMenu = $derived(
    actionItems.length > 0 &&
      auth.isAuthenticated &&
      !loading &&
      !error &&
      items.length < SEARCH_THRESHOLD,
  );
</script>

<svelte:head>
  <title>{pageTitle(title)}</title>
  <link rel="preload" as="fetch" href={endpoint} crossorigin="anonymous" />
</svelte:head>

{#snippet actionsSnippet()}
  <EditSectionMenu items={actionItems} />
{/snippet}

<Page>
  <PageHeader
    {title}
    subtitle={headerSnippet ? undefined : subtitle}
    actions={showActionMenu ? actionsSnippet : undefined}
  >
    {#if headerSnippet}
      {@render headerSnippet()}
    {/if}
  </PageHeader>

  {#if loading}
    <StatusMessage variant="loading">Loading...</StatusMessage>
  {:else if error}
    <StatusMessage variant="error">Failed to load {entityLabel}.</StatusMessage>
  {:else}
    {#if showSearch}
      <SearchBox bind:value={searchQuery} placeholder={`Search ${entityLabel}...`} />
    {/if}

    {#if filters}
      {@render filters()}
    {/if}

    {#if items.length === 0}
      <StatusMessage variant="empty">No {entityLabel} found.</StatusMessage>
    {:else if filteredItems.length === 0}
      {#if createHref && auth.isAuthenticated && searchQuery.trim() !== ''}
        <NoResultsCreatePrompt
          entityLabel={singularLabel}
          query={searchQuery.trim()}
          createHref={`${createHref}?name=${encodeURIComponent(searchQuery.trim())}`}
        />
      {:else}
        <StatusMessage variant="empty">No matching {entityLabel}.</StatusMessage>
      {/if}
    {:else if listSnippet}
      {@render listSnippet(filteredItems)}
    {:else}
      <ul class="item-list">
        {#each filteredItems as item (item.slug)}
          <li>
            <a href={resolveHref(`${basePath}/${item.slug}`)} class="item-row">
              {#if rowSnippet}
                {@render rowSnippet(item)}
              {:else}
                <span class="item-name">{item.name}</span>
                {#if typeof item.title_count === 'number'}
                  <span class="count"
                    >{item.title_count} title{item.title_count === 1 ? '' : 's'}</span
                  >
                {/if}
              {/if}
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</Page>

<style>
  .item-list {
    list-style: none;
    padding: 0;
  }

  .item-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--size-4);
    padding: var(--size-3) 0;
    border-bottom: 1px solid var(--color-border-soft);
    text-decoration: none;
    color: var(--color-text);
  }

  .item-row:hover {
    color: var(--color-link);
  }

  .item-name {
    font-size: var(--font-size-2);
    color: inherit;
    font-weight: 500;
    flex: 1;
  }

  .count {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    flex-shrink: 0;
  }
</style>
