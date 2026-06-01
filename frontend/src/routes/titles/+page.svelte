<script lang="ts">
  import { afterNavigate, goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { page } from '$app/state';
  import { auth } from '$lib/auth.svelte';
  import ActiveFilterChips from '$lib/components/ActiveFilterChips.svelte';
  import FilterDrawer from '$lib/components/FilterDrawer.svelte';
  import NoResultsCreatePrompt from '$lib/components/NoResultsCreatePrompt.svelte';
  import SearchBox from '$lib/components/SearchBox.svelte';
  import TitleFilterSidebar from '$lib/components/TitleFilterSidebar.svelte';
  import { pageTitle } from '$lib/constants';
  import { filtersFromParams, filtersToParams, type FilterState } from '$lib/facet-engine';
  import { titleFilterChips } from './titles-filter-chips';
  import TitlesGrid from './TitlesGrid.svelte';
  import { decideCreatePrompt } from '$lib/create-prompt';
  import { streamed } from '$lib/streamed.svelte';

  let { data } = $props();

  // Resolve the streamed facet options into sticky reactive state. The sidebar mounts
  // once (disabled+empty on first/cold load), then hydrates options + counts when the
  // stream lands; on a re-filter the prior options stay visible until new counts settle,
  // so there's no skeleton flash. `data.filter_options` is a fresh promise per load.
  const facets = streamed(() => data.filter_options);

  // Stable identity of the current filter set (server-canonical field order),
  // used to remount the grid only when the filters change.
  let gridKey = $derived(JSON.stringify(data.query));

  // ---------------------------------------------------------------------
  // Filter state lives in the URL. `filters` is the authoritative reactive
  // copy bound by the sidebar; it's mirrored to the URL via `goto`, which
  // re-runs +page.server.ts (cards awaited, facets re-streamed). A filter
  // change is a plain client-side navigation — no client facet engine.
  // ---------------------------------------------------------------------
  function canonical(f: FilterState): string {
    return filtersToParams(f, new URLSearchParams()).toString();
  }

  // Seed from the request URL so a filtered URL renders the search box and
  // selected filters in the SSR HTML (page.url is the real URL on the server —
  // /titles is not prerendered). `filters` is then the authoritative mutable
  // copy the sidebar binds to.
  const initial = filtersFromParams(new URLSearchParams(page.url.search));
  let filters = $state<FilterState>(initial);
  // SearchBox binds here; debounced into `filters.query` so typing doesn't fire
  // a server navigation per keystroke. A writable `$derived` so it mirrors the
  // committed query when that changes from outside the input (the sidebar's
  // "Clear all", a popstate, the seed) but is still reassignable while typing.
  let queryInput = $derived(filters.query);
  let lastSyncedSearch = canonical(initial);

  // Back/forward adopt the URL as the source of truth (does NOT fire on our goto).
  afterNavigate((nav) => {
    if (nav.type !== 'popstate') return;
    const f = filtersFromParams(new URLSearchParams(page.url.search));
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

  // filters → URL navigation. Skipped when the URL already matches (the initial
  // seed, a popstate resync, or the landing of our own goto).
  $effect(() => {
    const search = canonical(filters);
    if (search === lastSyncedSearch) return;
    lastSyncedSearch = search;
    void goto(`${resolve('/titles')}${search ? `?${search}` : ''}`, {
      keepFocus: true,
      noScroll: true,
    });
  });

  // The "create?" prompt keys on the committed query (`data.query.q`, which the
  // streamed `query_count` was computed for) — not the mid-debounce `queryInput`.
  let createHref = $derived(
    `${resolve('/titles/new')}?name=${encodeURIComponent((data.query.q ?? '').trim())}`,
  );

  $effect(() => {
    void auth.load();
  });
</script>

<svelte:head>
  <title>{pageTitle('Titles')}</title>
</svelte:head>

<div class="titles-page">
  <SearchBox bind:value={queryInput} placeholder="Search titles..." />

  <div class="layout">
    <FilterDrawer label="Filter titles">
      <!-- The sidebar renders once, immediately (disabled+empty until the streamed
           options arrive). On a facet-endpoint failure the controls stay disabled and
           this inline error/retry sits alongside them, rather than replacing the pane. -->
      {#if facets.status === 'error'}
        <p class="sidebar-error">
          {facets.value ? 'Filters couldn’t be updated.' : 'Filters couldn’t be loaded.'}
          <button type="button" class="retry" onclick={() => invalidateAll()}>Retry</button>
        </p>
      {/if}
      <TitleFilterSidebar
        filterOptions={facets.value}
        disabled={facets.value === undefined}
        busy={facets.status === 'loading'}
        bind:filters
      />
    </FilterDrawer>

    <main class="results">
      {#if facets.value}
        <ActiveFilterChips chips={titleFilterChips(filters, facets.value)} />
      {/if}

      <p class="count">{data.count.toLocaleString()} {data.count === 1 ? 'title' : 'titles'}</p>

      <!-- Remount (reseed the loader to page 1) only when the filters actually
           change, not on every load re-run — keying on the whole `data` object
           would reset infinite scroll on any unrelated invalidation. -->
      {#key gridKey}
        <TitlesGrid initial={{ items: data.items, count: data.count }} query={data.query} />
      {/key}

      {#await data.query_count then queryCount}
        {@const prompt = decideCreatePrompt({
          query: data.query.q ?? '',
          isAuthenticated: auth.isAuthenticated,
          queryCount,
        })}
        {#if prompt.show}
          <NoResultsCreatePrompt entityLabel="title" query={prompt.query} {createHref} />
        {/if}
      {/await}
    </main>
  </div>
</div>

<style>
  .titles-page {
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
