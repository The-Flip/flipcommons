<script
  lang="ts"
  generics="F extends { query: string }, O, T extends { slug: string; name: string }"
>
  import type { Component, Snippet } from 'svelte';
  import { afterNavigate, goto, invalidateAll } from '$app/navigation';
  import { page } from '$app/state';
  import { auth } from '$lib/auth.svelte';
  import ActiveFilterChips, {
    type FilterChipSpec,
  } from '$lib/components/collections/filters/ActiveFilterChips.svelte';
  import FilterDrawer from '$lib/components/collections/filters/FilterDrawer.svelte';
  import NoResultsCreatePrompt from '$lib/components/NoResultsCreatePrompt.svelte';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import PaginatedListLoader from './PaginatedListLoader.svelte';
  import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';
  import MetaTags from '$lib/components/MetaTags.svelte';
  import JsonLd from '$lib/components/JsonLd.svelte';
  import { buildListingJsonLd, listingMeta } from '$lib/entities/schema-org';
  import { decideCreatePrompt } from '$lib/create-prompt';
  import { streamed } from '$lib/streamed.svelte';
  import { resolveHref } from '$lib/utils';

  /**
   * Shared shell for the faceted catalog listing pages (`/titles`,
   * `/manufacturers`). The faceted superset of `CatalogListing`/`PaginatedListPage`:
   * it owns the URL⇄filter-state loop (seed from the request URL, popstate resync,
   * debounced search, `goto` on any filter change), the streamed-facet sidebar
   * wiring + error/retry, the active chips, the count line, the `{#key}`-remounted
   * card-grid loader and the create-prompt. Each consuming page supplies only its
   * per-entity parts: the URL⇄state `engine`, the bindable `Sidebar`, the `chips`
   * builder, the `fetchPage` closure (path literal baked in, so `T` stays typed)
   * and the card `children` snippet.
   *
   * Catalog-coupled by design: it resolves `catalogKey` through `ENTITY_META`
   * rather than taking title/label props. The streamed facet options/counts are
   * unchanged from the per-page versions; this is a pure structural extraction.
   */
  let {
    catalogKey,
    engine,
    Sidebar,
    chips,
    filterOptions,
    queryCount,
    query,
    initial,
    fetchPage,
    children,
  }: {
    /** Catalog entity key; the heading, base path and singular/plural labels come from `ENTITY_META`. */
    catalogKey: CatalogEntityKey;
    /** URL⇄filter-state serialization for this entity's filter shape `F`. */
    engine: {
      fromParams: (sp: URLSearchParams) => F;
      toParams: (f: F, sp: URLSearchParams) => URLSearchParams;
    };
    /** The entity's filter sidebar — rendered with `bind:filters`, so its `filters` prop must be `$bindable()`. */
    Sidebar: Component<{
      filterOptions: O | undefined;
      disabled?: boolean;
      busy?: boolean;
      filters: F;
    }>;
    /** Builds the active-filter chips from the live filters + the resolved server options. */
    chips: (filters: F, options: O) => FilterChipSpec[];
    /** Streamed facet option lists with live counts; resolves to `undefined` on error (the load `.catch`es). */
    filterOptions: Promise<O | undefined>;
    /** Streamed query-only match count (ignores facets); drives the create prompt. */
    queryCount: Promise<number | null | undefined>;
    /** The committed query that produced page 1 (server-canonical); keys the grid and the create prompt. */
    query: { q?: string | null };
    /** SSR page 1 for the committed query; seeds the loader and the count line. */
    initial: { items: T[]; count: number };
    /** Typed page fetcher (path literal baked in by the caller). */
    fetchPage: (page: number) => Promise<{ items: T[]; count: number }>;
    /** The card for one item. */
    children: Snippet<[T]>;
  } = $props();

  let meta = $derived(ENTITY_META[catalogKey]);
  let basePath = $derived(`/${meta.entity_type_plural}`);
  let singularLabel = $derived(meta.label.toLowerCase());
  let pluralLabel = $derived(meta.label_plural.toLowerCase());

  // Resolve the streamed facet options into sticky reactive state. The sidebar
  // mounts once (disabled+empty on first/cold load), then hydrates options +
  // counts when the stream lands; on a re-filter the prior options stay visible
  // until new counts settle, so there's no skeleton flash. `filterOptions` is a
  // fresh promise per load.
  const facets = streamed(() => filterOptions);

  // Stable identity of the current filter set (server-canonical field order).
  // Keys the grid's `{#key}` so the loader reseeds to page 1 only when the
  // filters actually change — keying on the whole `data`/load result would
  // reset infinite scroll on any unrelated invalidation.
  let gridKey = $derived(JSON.stringify(query));

  // ---------------------------------------------------------------------
  // Filter state lives in the URL. `filters` is the authoritative reactive copy
  // bound by the sidebar; it's mirrored to the URL via `goto`, which re-runs
  // +page.server.ts (cards awaited, facets re-streamed). A filter change is a
  // plain client-side navigation — no client facet engine.
  // ---------------------------------------------------------------------
  function canonical(f: F): string {
    return engine.toParams(f, new URLSearchParams()).toString();
  }

  // Seed from the request URL so a filtered URL renders the search box and
  // selected filters in the SSR HTML (page.url is the real URL on the server).
  // `engine` is a static per-page prop, so reading it once at construction is intended.
  // svelte-ignore state_referenced_locally
  const seed = engine.fromParams(new URLSearchParams(page.url.search));
  let filters = $state<F>(seed);
  // SearchBox binds here; debounced into `filters.query` so typing doesn't fire a
  // server navigation per keystroke. A writable `$derived` so it mirrors the
  // committed query when that changes from outside the input (Clear all,
  // popstate, the seed) but is still reassignable while typing.
  let queryInput = $derived(filters.query);
  let lastSyncedSearch = canonical(seed);

  // Back/forward adopt the URL as the source of truth (does NOT fire on our goto).
  afterNavigate((nav) => {
    if (nav.type !== 'popstate') return;
    const f = engine.fromParams(new URLSearchParams(page.url.search));
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
    void goto(`${resolveHref(basePath)}${search ? `?${search}` : ''}`, {
      keepFocus: true,
      noScroll: true,
    });
  });

  // The "create?" prompt keys on the committed query (`query.q`, which the
  // streamed `query_count` was computed for) — not the mid-debounce `queryInput`.
  let createHref = $derived(
    `${resolveHref(`${basePath}/new`)}?name=${encodeURIComponent((query.q ?? '').trim())}`,
  );

  $effect(() => {
    void auth.load();
  });

  let listingCopy = $derived(listingMeta(catalogKey));
  let listingJsonLd = $derived(
    buildListingJsonLd(catalogKey, initial.items, page.url, initial.count),
  );
</script>

<MetaTags
  title={listingCopy.title}
  description={listingCopy.description}
  url={page.url.href}
  ogType="website"
/>
<JsonLd data={listingJsonLd} />

<div class="faceted-page">
  <h1>{listingCopy.heading}</h1>

  <SearchBox bind:value={queryInput} placeholder={`Search ${pluralLabel}...`} />

  <div class="layout">
    <FilterDrawer label={`Filter ${pluralLabel}`}>
      <!-- The sidebar renders once, immediately (disabled+empty until the streamed
           options arrive). On a facet-endpoint failure the controls stay disabled and
           this inline error/retry sits alongside them, rather than replacing the pane. -->
      {#if facets.status === 'error'}
        <p class="sidebar-error">
          {facets.value ? 'Filters couldn’t be updated.' : 'Filters couldn’t be loaded.'}
          <button type="button" class="retry" onclick={() => invalidateAll()}>Retry</button>
        </p>
      {/if}
      <Sidebar
        filterOptions={facets.value}
        disabled={facets.value === undefined}
        busy={facets.status === 'loading'}
        bind:filters
      />
    </FilterDrawer>

    <main class="results">
      {#if facets.value}
        <ActiveFilterChips chips={chips(filters, facets.value)} />
      {/if}

      <p class="count">
        {initial.count.toLocaleString()}
        {initial.count === 1 ? singularLabel : pluralLabel}
      </p>

      <!-- Remount (reseed the loader to page 1) only when the filters actually change. -->
      {#key gridKey}
        <PaginatedListLoader {initial} {fetchPage} {basePath} layout="card" {children} />
      {/key}

      {#await queryCount then count}
        {@const prompt = decideCreatePrompt({
          query: query.q ?? '',
          isAuthenticated: auth.isAuthenticated,
          queryCount: count,
        })}
        {#if prompt.show}
          <NoResultsCreatePrompt entityLabel={singularLabel} query={prompt.query} {createHref} />
        {/if}
      {/await}
    </main>
  </div>
</div>

<style>
  .faceted-page {
    padding: var(--size-5) 0;
  }

  h1 {
    margin-bottom: var(--size-4);
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
