<script lang="ts" generics="T extends { slug: string }">
  import type { Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import { auth } from '$lib/auth.svelte';
  import Page from '$lib/components/layout/page/Page.svelte';
  import PageHeader from '$lib/components/layout/page/PageHeader.svelte';
  import SearchBox from '$lib/components/ui/SearchBox.svelte';
  import StatusMessage from '$lib/components/ui/StatusMessage.svelte';
  import EditSectionMenu from '$lib/components/layout/page/EditSectionMenu.svelte';
  import NoResultsCreatePrompt from './NoResultsCreatePrompt.svelte';
  import PaginatedCardLoader from './PaginatedCardLoader.svelte';
  import PaginatedListLoader from './PaginatedListLoader.svelte';
  import type { EditSectionMenuItem } from '$lib/components/layout/page/edit-section-menu';
  import { SEARCH_THRESHOLD } from '$lib/components/collections/grid/search-threshold';
  import { resolveHref } from '$lib/utils';

  /**
   * Generic SSR controller for a server-paginated row-list page. Owns all the
   * list behavior — seeds search from the SSR-loaded `q`, mirrors typing into a
   * debounced `goto ?q=` (which re-runs the page's server load), hosts the
   * seeded infinite-scroll loader (remounted via `{#key}` on a search change),
   * and renders the threshold-gated search box, empty states and create
   * affordances.
   *
   * Entity-agnostic by construction: it takes plain presentation props (title,
   * labels, base path) rather than looking anything up, so it never imports the
   * catalog registry. `CatalogListing` is the thin adapter that maps a
   * `catalogKey` onto these props; a non-catalog list (e.g. users) supplies
   * them directly. The caller provides a typed `fetchPage` closure (path
   * literal baked in, so `T` stays typed) and a row `children` snippet.
   *
   * Emits no `<head>` metadata: the adapter owns title/description/canonical
   * (`CatalogListing` via `MetaTags` + `JsonLd`), so a non-catalog adapter must
   * supply its own.
   */
  let {
    title,
    subtitle,
    basePath,
    singularLabel,
    singularTitle,
    initial,
    fetchPage,
    q,
    canCreate = false,
    layout = 'row',
    extraParams = {},
    extraFilter,
    headerSnippet,
    children,
  }: {
    /** Plural display label, e.g. "Franchises" — the page heading and `<title>`. */
    title: string;
    subtitle?: string;
    /** Detail-page base, e.g. `/franchises`; rows link to `${basePath}/${slug}`. */
    basePath: string;
    /** Lowercase singular, e.g. "franchise" — used in the create prompt. */
    singularLabel: string;
    /** Title-case singular, e.g. "Franchise" — used in the "+ New X" menu. */
    singularTitle: string;
    /** SSR page 1 for the committed `q`; seeds the loader and drives the count-based gates. */
    initial: { items: T[]; count: number };
    fetchPage: (page: number) => Promise<{ items: T[]; count: number }>;
    /** Committed search term from the SSR load (URL-derived); '' when unfiltered. */
    q: string;
    canCreate?: boolean;
    /** `'row'` (linked text rows, default) or `'card'` (a card grid, e.g. people). */
    layout?: 'row' | 'card';
    /**
     * Committed extra URL query params beyond `q` (e.g. systems'
     * `{ manufacturer }`), URL-derived from the SSR load. The controller is the
     * single navigator: it preserves these in the debounced `q` `goto`, folds
     * them into the loader remount key (so changing one reseeds to page 1) and
     * derives `extraFilterActive` from them (a non-empty value suppresses the
     * create prompt — `count === 0` under a filter doesn't mean the name is free).
     * Default `{}` keeps every plain list page unaffected.
     */
    extraParams?: Record<string, string>;
    /**
     * Optional control rendered beside the search box (e.g. systems' manufacturer
     * `<select>`). Receives `setExtra`, the controller's navigate callback — call
     * it with the changed params (e.g. `{ manufacturer: slug }`) to commit a new
     * URL preserving the current `q`. Keeps URL-building solely in the controller.
     */
    extraFilter?: Snippet<[(extra: Record<string, string>) => void]>;
    headerSnippet?: Snippet;
    children: Snippet<[T]>;
  } = $props();

  let entityLabel = $derived(title.toLowerCase());

  // SearchBox binds here. A writable `$derived` so it mirrors the committed `q`
  // when that changes from outside the input (a popstate, the seed, our goto's
  // landing) yet stays reassignable while typing.
  let queryInput = $derived(q);

  // Stable string view of the committed extra params, for the remount key.
  let extraParamsKey = $derived(
    Object.entries(extraParams)
      .filter(([, value]) => value)
      .map(([key, value]) => `${key}=${value}`)
      .join('&'),
  );

  // Remount the loader (reseed to page 1) when the committed search *or* an
  // extra filter (e.g. manufacturer) changes — both narrow the server page.
  let gridKey = $derived(`${q}|${extraParamsKey}`);

  // Any non-empty extra filter value (e.g. a selected manufacturer). Drives
  // create-prompt suppression: under an active filter `count === 0` means "none
  // match the filter", not "the name is free".
  let extraFilterActive = $derived(Object.values(extraParams).some((value) => value !== ''));

  $effect(() => {
    void auth.load();
  });

  // Single navigator: the controller owns all URL-building so `q` and the extra
  // params never clobber each other. Both the debounced search and the
  // `extraFilter`'s `setExtra` callback route through here; `goto` re-runs the
  // page's server load, which feeds fresh `q`/`extraParams` back in via props.
  function buildHref(nextQ: string, nextExtra: Record<string, string>): string {
    const pairs: string[] = [];
    if (nextQ) pairs.push(`q=${encodeURIComponent(nextQ)}`);
    for (const [key, value] of Object.entries(nextExtra)) {
      if (value) pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
    }
    return `${resolveHref(basePath)}${pairs.length ? `?${pairs.join('&')}` : ''}`;
  }
  function navigate(nextQ: string, nextExtra: Record<string, string>): void {
    void goto(buildHref(nextQ, nextExtra), { keepFocus: true, noScroll: true });
  }

  // Commit an extra-filter change immediately (no debounce — it's a discrete
  // select, not keystrokes), preserving the current committed `q`.
  function setExtra(extra: Record<string, string>): void {
    navigate(q.trim(), { ...extraParams, ...extra });
  }

  // Back/forward re-runs the server load, so `q` (hence `queryInput`/`gridKey`)
  // adopts the URL reactively via the props — no `afterNavigate` resync needed
  // (unlike titles, whose local filter state must be re-read from the URL).

  // Debounce typing → one `goto ?q=` per pause, preserving any active extra
  // filter. Skipped when the input already matches the committed `q` (seed /
  // popstate / our goto's landing, each of which resets `queryInput` via the
  // `$derived(q)` above), so no echo loop.
  let qTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = queryInput.trim();
    if (next === q) return;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => navigate(next, extraParams), 250);
    return () => clearTimeout(qTimer);
  });

  // Search box appears once the set is big enough to need it, or whenever a
  // query is active (so a narrowed result set keeps its box). Based on the
  // server `count`, not page-1 length.
  let showSearch = $derived(initial.count >= SEARCH_THRESHOLD || q.trim() !== '');

  // Below the threshold there's no search box, so creation is offered via a
  // header "+ New X" menu instead (auth-gated), mirroring the taxonomy pages.
  let createHref = $derived(canCreate ? `${basePath}/new` : undefined);
  let actionItems: EditSectionMenuItem[] = $derived(
    createHref
      ? [{ key: 'new', label: `+ New ${singularTitle}`, href: resolveHref(createHref) }]
      : [],
  );
  // The header "+ New" menu is the alternative to the search box (shown only
  // below the threshold), so it must hide whenever a search is active —
  // otherwise a `?q=` URL on a small entity would surface both at once.
  let showActionMenu = $derived(
    actionItems.length > 0 &&
      auth.isAuthenticated &&
      q.trim() === '' &&
      initial.count < SEARCH_THRESHOLD,
  );

  // With no facets, `count === 0 && q` unambiguously means the name is free, so
  // the create offer is correct without a separate query-only count — *unless*
  // an extra filter is active (e.g. a manufacturer), where `count === 0` means
  // "none under this filter", not "the name is free", so suppress it.
  let showCreatePrompt = $derived(
    !!createHref &&
      auth.isAuthenticated &&
      q.trim() !== '' &&
      initial.count === 0 &&
      !extraFilterActive,
  );
</script>

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

  {#if showSearch}
    <SearchBox bind:value={queryInput} placeholder={`Search ${entityLabel}...`} />
  {/if}

  <!-- Rendered independently of the search box: an extra filter (e.g.
       manufacturer) is its own control and stays available below the search
       threshold. The snippet owns its markup and calls `setExtra` to navigate. -->
  {#if extraFilter}
    {@render extraFilter(setExtra)}
  {/if}

  {#if initial.count === 0}
    {#if showCreatePrompt}
      <NoResultsCreatePrompt
        entityLabel={singularLabel}
        query={q.trim()}
        createHref={`${createHref}?name=${encodeURIComponent(q.trim())}`}
      />
    {:else if q.trim() !== ''}
      <StatusMessage variant="empty">No matching {entityLabel}.</StatusMessage>
    {:else}
      <StatusMessage variant="empty">No {entityLabel} found.</StatusMessage>
    {/if}
  {:else}
    {#key gridKey}
      {#if layout === 'card'}
        <PaginatedCardLoader {initial} {fetchPage} {children} />
      {:else}
        <PaginatedListLoader {initial} {fetchPage} {basePath} {children} />
      {/if}
    {/key}
  {/if}
</Page>
