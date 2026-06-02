<script lang="ts" generics="T extends { slug: string; name: string; aliases?: string[] }">
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
  import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';

  interface Props {
    /** Catalog entity key. Title, basePath, singular/plural labels, and endpoint are derived from ENTITY_META. */
    catalogKey: CatalogEntityKey;
    subtitle?: string;
    items: T[];
    /** Server-loaded by default; the props exist for any client-loaded caller. */
    loading?: boolean;
    error?: string | null;
    headerSnippet?: Snippet;
    /**
     * Renders the list body — the filtered, search-narrowed item list is
     * passed in. The two remaining consumers (display-types,
     * technology-generations) supply a `GroupedTaxonomyList`. Header, search,
     * filters, and empty states remain handled by this component.
     */
    listSnippet?: Snippet<[items: T[]]>;
    /**
     * When true, the page renders create affordances (auth-gated) pointing
     * at `/{entity_type_plural}/new`:
     *  - below SEARCH_THRESHOLD: a "+ New {entity}" link in the header
     *  - at/above the threshold: a SearchBox; zero-match renders
     *    NoResultsCreatePrompt with the typed query.
     */
    canCreate?: boolean;
  }

  let {
    catalogKey,
    subtitle,
    items,
    loading = false,
    error = null,
    headerSnippet,
    listSnippet,
    canCreate = false,
  }: Props = $props();

  let meta = $derived(ENTITY_META[catalogKey]);
  let title = $derived(meta.label_plural);
  let basePath = $derived(`/${meta.entity_type_plural}`);
  let entityLabel = $derived(meta.label_plural.toLowerCase());
  let singularLabel = $derived(meta.label.toLowerCase());
  let singularTitle = $derived(meta.label);
  let createHref = $derived(canCreate ? `${basePath}/new` : undefined);

  let searchQuery = $state('');

  $effect(() => {
    void auth.load();
  });

  let showSearch = $derived(items.length >= SEARCH_THRESHOLD || searchQuery.trim() !== '');

  let filteredItems = $derived.by(() => {
    const q = normalizeText(searchQuery.trim());
    if (!q) return items;
    // Per RecordCreateDelete.md:115, aliases must count as results for the
    // duplicate-prevention gate — otherwise a search for an existing alias
    // would wrongly trigger NoResultsCreatePrompt.
    return items.filter((item) => {
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
    {/if}
  {/if}
</Page>
