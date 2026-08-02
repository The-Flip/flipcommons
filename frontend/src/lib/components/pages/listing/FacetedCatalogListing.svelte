<script lang="ts" generics="F extends { q: string }, O, T extends ListingJsonLdItem">
  import type { Component, Snippet } from 'svelte';
  import { goto, invalidateAll } from '$app/navigation';
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
  import { searchDraft } from '$lib/search-draft.svelte';
  import { streamed } from '$lib/streamed.svelte';
  import { resolveHref } from '$lib/utils';

  /**
   * Shared shell for the faceted catalog listing pages (`/games`,
   * `/manufacturers`). The faceted superset of `CatalogListing`/`PaginatedListPage`:
   * it owns the filter state (derived from the URL, patched via `goto` intents),
   * the debounced search draft, the streamed-facet sidebar wiring + error/retry,
   * the active chips, the count line, the `{#key}`-remounted card-grid loader and
   * the create-prompt. Each consuming page supplies only its per-entity parts:
   * the URL⇄state `engine`, the `Sidebar`, the `chips` builder, the `fetchPage`
   * closure (path literal baked in, so `T` stays typed) and the card `children`
   * snippet.
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
    /** The entity's filter sidebar — reads `filters`, requests changes via `onchange`. */
    Sidebar: Component<{
      filterOptions: O | undefined;
      disabled?: boolean;
      busy?: boolean;
      filters: F;
      onchange: (patch: Partial<F>) => void;
    }>;
    /**
     * Builds the active-filter chips from the live filters + the resolved
     * server options — called with `undefined` options while the facet stream
     * is pending or failed, so the chip row (the only removal affordance for
     * chip-only dimensions) never depends on the facet payload. Each chip's
     * `remove` requests the change through `apply`.
     */
    chips: (
      filters: F,
      options: O | undefined,
      apply: (patch: Partial<F>) => void,
    ) => FilterChipSpec[];
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
  // Filter state lives in the URL and is derived from it — there is no
  // writable copy to fall out of sync, so back/forward, link navigations and
  // our own goto landings are all the same event: the URL changed. While one
  // of our own filter navigations is in flight, `pending` holds its target so
  // controls render — and further intents compose on — the requested state
  // rather than the still-committed URL. `$state.raw` because settlement
  // matches intents by object identity.
  // ---------------------------------------------------------------------
  let pending = $state.raw<{ href: string; search: string } | null>(null);
  let filters = $derived(
    engine.parse(pending ? new URLSearchParams(pending.search) : page.url.searchParams),
  );

  /**
   * Apply a filter intent: compose the patch on the rendered state and
   * navigate to the result. The landing updates `page.url`, which is what
   * re-derives `filters`; a no-op patch doesn't navigate. `pending` clears
   * when the `goto` settles — SvelteKit settles it on landing, error and
   * supersession alike — guarded by identity so an earlier intent's
   * settlement never clears a newer intent's pending. A navigation that
   * settles without landing (blocked, or aborted by an invalidation) snaps
   * the rendered state back to the URL's, which is also the honest outcome.
   */
  function apply(patch: Partial<F>) {
    const next = { ...filters, ...patch };
    const search = engine.canonical(next);
    if (search === engine.canonical(filters)) return;
    const intent = { href: `${resolveHref(navPath)}${search ? `?${search}` : ''}`, search };
    pending = intent;
    void goto(intent.href, { keepFocus: true, noScroll: true }).finally(() => {
      if (pending === intent) pending = null;
    });
  }

  // The search box holds a draft ahead of the committed query; committing is
  // a filter intent like any other, round-tripping through the URL. The
  // committed value is read from the pending-aware `filters`, so our own
  // commit changes it in the same tick (the landing is a no-op for the box)
  // and a stale landing while a newer intent is pending can't rewind it.
  const queryDraft = searchDraft(
    () => filters.q,
    (q) => apply(Object.assign({}, filters, { q })),
  );

  // The "create?" prompt keys on the committed query (`query.q`, which the
  // streamed `query_count` was computed for) — not the mid-debounce draft.
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

  <SearchBox
    bind:value={queryDraft.value}
    placeholder={`Search ${listingCopy.itemLabelPlural}...`}
  />

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
        {filters}
        onchange={apply}
      />
    </FilterDrawer>

    <main class="results">
      <ActiveFilterChips chips={chips(filters, facets.value, apply)} />

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
