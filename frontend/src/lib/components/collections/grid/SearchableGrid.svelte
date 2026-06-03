<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import CardGrid from './CardGrid.svelte';
  import ClientFilteredGrid from './ClientFilteredGrid.svelte';
  import SkeletonCard from '$lib/components/collections/cards/SkeletonCard.svelte';
  import { normalizeText } from '$lib/utils';
  import { SEARCH_THRESHOLD } from './search-threshold';

  const SKELETON_INDICES = Array.from({ length: 12 }, (_, i) => i);

  let {
    items,
    filterFields,
    loading = false,
    error = null,
    placeholder = 'Search...',
    entityName = 'result',
    entityNamePlural = `${entityName}s`,
    children,
    noResultsPrompt,
  }: {
    items: T[];
    filterFields: (item: T) => (string | number | null | undefined)[];
    loading?: boolean;
    error?: string | null;
    placeholder?: string;
    entityName?: string;
    entityNamePlural?: string;
    children: Snippet<[T]>;
    // Rendered when the user has typed a non-empty query and the filter
    // produced zero matches. The trimmed query is passed in so the caller
    // can echo it in "Create {query}?" affordances.
    noResultsPrompt?: Snippet<[string]>;
  } = $props();

  let searchQuery = $state('');

  let filteredItems = $derived.by(() => {
    const q = normalizeText(searchQuery.trim());
    if (!q) return items;
    return items.filter((item) =>
      filterFields(item).some((field) => field != null && normalizeText(String(field)).includes(q)),
    );
  });

  let showSearch = $derived(items.length >= SEARCH_THRESHOLD || searchQuery.trim() !== '');
</script>

<div class="searchable-grid">
  {#if loading}
    {#if showSearch}
      <SearchBox {placeholder} disabled />
    {/if}
    <CardGrid>
      {#each SKELETON_INDICES as i (i)}
        <SkeletonCard />
      {/each}
    </CardGrid>
  {:else if error}
    <p class="error">{error}</p>
  {:else}
    {#if showSearch}
      <SearchBox bind:value={searchQuery} {placeholder} />
    {/if}

    <ClientFilteredGrid items={filteredItems} {entityName} {entityNamePlural} {children} />

    {#if noResultsPrompt && filteredItems.length === 0 && searchQuery.trim() !== ''}
      {@render noResultsPrompt(searchQuery.trim())}
    {/if}
  {/if}
</div>

<style>
  .searchable-grid {
    padding: var(--size-5) 0;
  }

  .error {
    text-align: center;
    color: var(--color-error-text);
    padding: var(--size-6) 0;
  }
</style>
