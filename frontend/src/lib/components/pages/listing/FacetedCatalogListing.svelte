<script lang="ts" generics="F extends { q: string }, O, T extends ListingJsonLdItem">
  import type { Component, Snippet } from 'svelte';
  import { afterNavigate, goto, invalidateAll } from '$app/navigation';
  import { page } from '$app/state';
  import { auth } from '$lib/auth.svelte';
  import ActiveFilterChips, {
    type FilterChipSpec,
  } from '$lib/components/collections/filters/ActiveFilterChips.svelte';
  import FilterDrawer from '$lib/components/collections/filters/FilterDrawer.svelte';
  import NoResultsCreatePrompt from './NoResultsCreatePrompt.svelte';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import PaginatedCardLoader from './PaginatedCardLoader.svelte';
  import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';
  import MetaTags from '$lib/components/layout/page/head/MetaTags.svelte';
  import JsonLd from '$lib/components/layout/page/head/JsonLd.svelte';
  import {
    buildListingJsonLd,
    listingMeta,
    type ListingJsonLdItem,
  } from '$lib/entities/schema-org';
  import { decideCreatePrompt } from '$lib/create-prompt';
  import type { FilterCodec } from '$lib/filters/params';
  import { listingPath } from '$lib/entities/listing-path';
  import { streamed } from '$lib/streamed.svelte';
  import { resolveHref } from '$lib/utils';

  /**
   * Shared shell for the faceted catalog listing pages (`/games`,
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
   * rather than taking title/label props.
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
    /** The entity's filter codec: URL⇄filter-state serialization for its filter shape `F`. */
    engine: FilterCodec<F>;
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
  // Two distinct paths: filter navigation goes to the listing (which may be
  // overridden — `/games`), while creation lives under the entity's own
  // segment (`/titles/new`), because what the listing creates is the entity.
  let navPath = $derived(listingPath(catalogKey));
  let createBasePath = $derived(`/${meta.entity_type_plural}`);
  // What one listing ROW is called (a "game" can be a Title or a Model); the
  // create prompt keeps the entity label, because what it creates is a Title.
  let entityLabel = $derived(meta.label.toLowerCase());

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
  // Seed from the request URL so a filtered URL renders the search box and
  // selected filters in the SSR HTML (page.url is the real URL on the server).
  // `engine` is a static per-page prop, so reading it once at construction is intended.
  // svelte-ignore state_referenced_locally
  const seed = engine.parse(new URLSearchParams(page.url.search));
  let filters = $state<F>(seed);
  // Debounced into `filters.q` so typing doesn't fire a server navigation
  // per keystroke, and mirrors it back when it changes from outside (Clear all,
  // popstate, the seed). Mirroring is safe only because that commit is local
  // state landing in the same tick — a box whose commit round-trips through the
  // URL must use `searchDraft`, or a landing rewinds the box mid-word.
  let queryInput = $derived(filters.q);
  // svelte-ignore state_referenced_locally
  let lastSyncedSearch = engine.canonical(seed);

  // Any navigation that lands on a URL our state doesn't match adopts the URL
  // as the source of truth — back/forward, and link navigations to this same
  // route (top-nav "Games" while filtered keeps the component instance, so
  // `filters` would otherwise stay stale). Our own goto landings and the
  // initial navigation compare equal and fall through.
  afterNavigate(() => {
    const f = engine.parse(new URLSearchParams(page.url.search));
    if (engine.canonical(f) === lastSyncedSearch) return;
    filters = f;
    lastSyncedSearch = engine.canonical(f);
  });

  // Debounce typing → committed query (one server navigation per pause).
  let qTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const q = queryInput;
    if (q === filters.q) return;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => (filters.q = q), 250);
    return () => clearTimeout(qTimer);
  });

  // filters → URL navigation. Skipped when the URL already matches (the initial
  // seed, a popstate resync, or the landing of our own goto).
  $effect(() => {
    const search = engine.canonical(filters);
    if (search === lastSyncedSearch) return;
    lastSyncedSearch = search;
    void goto(`${resolveHref(navPath)}${search ? `?${search}` : ''}`, {
      keepFocus: true,
      noScroll: true,
    });
  });

  // The "create?" prompt keys on the committed query (`query.q`, which the
  // streamed `query_count` was computed for) — not the mid-debounce `queryInput`.
  let createHref = $derived(
    `${resolveHref(`${createBasePath}/new`)}?name=${encodeURIComponent((query.q ?? '').trim())}`,
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

  <SearchBox bind:value={queryInput} placeholder={`Search ${listingCopy.itemLabelPlural}...`} />

  <div class="layout">
    <FilterDrawer label={`Filter ${listingCopy.itemLabelPlural}`}>
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
        {initial.count === 1 ? listingCopy.itemLabel : listingCopy.itemLabelPlural}
      </p>

      <!-- Remount (reseed the loader to page 1) only when the filters actually change. -->
      {#key gridKey}
        <PaginatedCardLoader {initial} {fetchPage} {children} />
      {/key}

      {#await queryCount then count}
        {@const prompt = decideCreatePrompt({
          query: query.q ?? '',
          isAuthenticated: auth.isAuthenticated,
          queryCount: count,
        })}
        {#if prompt.show}
          <NoResultsCreatePrompt {entityLabel} query={prompt.query} {createHref} />
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
