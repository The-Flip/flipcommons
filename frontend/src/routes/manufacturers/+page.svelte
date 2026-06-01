<script lang="ts">
  import { afterNavigate, goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { page } from '$app/state';
  import { auth } from '$lib/auth.svelte';
  import ActiveFilterChips from '$lib/components/ActiveFilterChips.svelte';
  import FilterDrawer from '$lib/components/FilterDrawer.svelte';
  import NoResultsCreatePrompt from '$lib/components/NoResultsCreatePrompt.svelte';
  import SearchBox from '$lib/components/SearchBox.svelte';
  import SidebarSkeleton from '$lib/components/SidebarSkeleton.svelte';
  import ManufacturerFilterSidebar from '$lib/components/ManufacturerFilterSidebar.svelte';
  import { pageTitle } from '$lib/constants';
  import {
    mfrFiltersFromParams,
    mfrFiltersToParams,
    type MfrFilterState,
  } from '$lib/manufacturer-facet-engine';
  import { manufacturerFilterChips } from './manufacturer-filter-chips';
  import ManufacturersGrid from './ManufacturersGrid.svelte';
  import { decideCreatePrompt } from '$lib/create-prompt';

  let { data } = $props();

  // Stable identity of the current filter set (server-canonical field order), used to
  // remount the grid only when the filters change.
  let gridKey = $derived(JSON.stringify(data.query));

  // ---------------------------------------------------------------------
  // Filter state lives in the URL. `filters` is the authoritative reactive copy bound
  // by the sidebar; it's mirrored to the URL via `goto`, which re-runs
  // +page.server.ts (cards awaited, facets re-streamed). Mirrors /titles.
  // ---------------------------------------------------------------------
  function canonical(f: MfrFilterState): string {
    return mfrFiltersToParams(f, new URLSearchParams()).toString();
  }

  // Seed from the request URL so a filtered URL renders the search box and selected
  // filters in the SSR HTML (page.url is the real URL on the server).
  const initial = mfrFiltersFromParams(new URLSearchParams(page.url.search));
  let filters = $state<MfrFilterState>(initial);
  // SearchBox binds here; debounced into `filters.query` so typing doesn't fire a
  // server navigation per keystroke. A writable `$derived` so it mirrors the committed
  // query when that changes from outside the input (Clear all, popstate, the seed).
  let queryInput = $derived(filters.query);
  let lastSyncedSearch = canonical(initial);

  // Back/forward adopt the URL as source of truth (does NOT fire on our goto).
  afterNavigate((nav) => {
    if (nav.type !== 'popstate') return;
    const f = mfrFiltersFromParams(new URLSearchParams(page.url.search));
    filters = f;
    lastSyncedSearch = canonical(f);
  });

  // Debounce typing → committed query (one server navigation per pause).
  let qTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const q = queryInput;
    if (q === filters.query) return;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => (filters.query = q), 250);
    return () => clearTimeout(qTimer);
  });

  // filters → URL navigation. Skipped when the URL already matches (the initial seed,
  // a popstate resync, or the landing of our own goto).
  $effect(() => {
    const search = canonical(filters);
    if (search === lastSyncedSearch) return;
    lastSyncedSearch = search;
    void goto(`${resolve('/manufacturers')}${search ? `?${search}` : ''}`, {
      keepFocus: true,
      noScroll: true,
    });
  });

  // The "create?" prompt keys on the committed query (`data.query.q`, which the
  // streamed `query_count` was computed for) — not the mid-debounce `queryInput`.
  let createHref = $derived(
    `${resolve('/manufacturers/new')}?name=${encodeURIComponent((data.query.q ?? '').trim())}`,
  );

  $effect(() => {
    void auth.load();
  });
</script>

<svelte:head>
  <title>{pageTitle('Manufacturers')}</title>
</svelte:head>

<div class="manufacturers-page">
  <SearchBox bind:value={queryInput} placeholder="Search manufacturers..." />

  <div class="layout">
    <FilterDrawer label="Filter manufacturers">
      {#await data.filter_options}
        <SidebarSkeleton />
      {:then filterOptions}
        {#if filterOptions}
          <ManufacturerFilterSidebar {filterOptions} bind:filters />
        {:else}
          <!-- Resolved to undefined = the facet endpoint failed (the cards, on the
               critical path, already loaded). Show a real error, not the pulsing
               skeleton, which would read as "still loading" forever. -->
          <p class="sidebar-error">
            Filters couldn’t be loaded.
            <button type="button" class="retry" onclick={() => invalidateAll()}>Retry</button>
          </p>
        {/if}
      {/await}
    </FilterDrawer>

    <main class="results">
      {#await data.filter_options then filterOptions}
        {#if filterOptions}
          <ActiveFilterChips chips={manufacturerFilterChips(filters, filterOptions)} />
        {/if}
      {/await}

      <p class="count">
        {data.count.toLocaleString()}
        {data.count === 1 ? 'manufacturer' : 'manufacturers'}
      </p>

      <!-- Remount (reseed the loader to page 1) only when the filters actually change. -->
      {#key gridKey}
        <ManufacturersGrid initial={{ items: data.items, count: data.count }} query={data.query} />
      {/key}

      {#await data.query_count then queryCount}
        {@const prompt = decideCreatePrompt({
          query: data.query.q ?? '',
          isAuthenticated: auth.isAuthenticated,
          queryCount,
        })}
        {#if prompt.show}
          <NoResultsCreatePrompt entityLabel="manufacturer" query={prompt.query} {createHref} />
        {/if}
      {/await}
    </main>
  </div>
</div>

<style>
  .manufacturers-page {
    padding: var(--size-5) 0;
  }

  .layout {
    display: grid;
    grid-template-columns: 16rem 1fr;
    gap: var(--size-5);
    align-items: start;
  }

  .results {
    min-width: 0;
  }

  .count {
    text-align: center;
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
    margin-bottom: var(--size-4);
  }

  .sidebar-error {
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
  }

  .retry {
    background: none;
    border: none;
    padding: 0;
    color: var(--color-link);
    font: inherit;
    cursor: pointer;
  }

  .retry:hover {
    text-decoration: underline;
  }

  @media (--breakpoint-narrow) {
    .layout {
      grid-template-columns: 1fr;
    }
  }
</style>
