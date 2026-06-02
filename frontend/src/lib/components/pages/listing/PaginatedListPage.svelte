<script lang="ts" generics="T extends { slug: string }">
  import type { Snippet } from 'svelte';
  import { goto } from '$app/navigation';
  import { auth } from '$lib/auth.svelte';
  import Page from '$lib/components/Page.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import SearchBox from '$lib/components/SearchBox.svelte';
  import StatusMessage from '$lib/components/StatusMessage.svelte';
  import EditSectionMenu from '$lib/components/EditSectionMenu.svelte';
  import NoResultsCreatePrompt from '$lib/components/NoResultsCreatePrompt.svelte';
  import PaginatedListLoader from './PaginatedListLoader.svelte';
  import type { EditSectionMenuItem } from '$lib/components/edit-section-menu';
  import { SEARCH_THRESHOLD } from '$lib/components/grid/search-threshold';
  import { pageTitle } from '$lib/constants';
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
    headerSnippet?: Snippet;
    children: Snippet<[T]>;
  } = $props();

  let entityLabel = $derived(title.toLowerCase());

  // SearchBox binds here. A writable `$derived` so it mirrors the committed `q`
  // when that changes from outside the input (a popstate, the seed, our goto's
  // landing) yet stays reassignable while typing.
  let queryInput = $derived(q);

  // Remount the loader (reseed to page 1) only when the committed search changes.
  let gridKey = $derived(q);

  $effect(() => {
    void auth.load();
  });

  // Back/forward re-runs the server load, so `q` (hence `queryInput`/`gridKey`)
  // adopts the URL reactively via the props — no `afterNavigate` resync needed
  // (unlike titles, whose local filter state must be re-read from the URL).

  // Debounce typing → one `goto ?q=` per pause. Skipped when the input already
  // matches the committed `q` (seed / popstate / our goto's landing, each of
  // which resets `queryInput` via the `$derived(q)` above), so no echo loop.
  let qTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const next = queryInput.trim();
    if (next === q) return;
    clearTimeout(qTimer);
    qTimer = setTimeout(() => {
      void goto(`${resolveHref(basePath)}${next ? `?q=${encodeURIComponent(next)}` : ''}`, {
        keepFocus: true,
        noScroll: true,
      });
    }, 250);
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
  // the create offer is correct without a separate query-only count.
  let showCreatePrompt = $derived(
    !!createHref && auth.isAuthenticated && q.trim() !== '' && initial.count === 0,
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

  {#if showSearch}
    <SearchBox bind:value={queryInput} placeholder={`Search ${entityLabel}...`} />
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
      <PaginatedListLoader {initial} {fetchPage} {basePath} {children} />
    {/key}
  {/if}
</Page>
