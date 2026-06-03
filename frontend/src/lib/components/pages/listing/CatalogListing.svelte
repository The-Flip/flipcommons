<script lang="ts" generics="T extends { slug: string; name: string }">
  import type { Snippet } from 'svelte';
  import { page } from '$app/state';
  import PaginatedListPage from './PaginatedListPage.svelte';
  import MetaTags from '$lib/components/layout/site/MetaTags.svelte';
  import JsonLd from '$lib/components/layout/site/JsonLd.svelte';
  import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';
  import { buildListingJsonLd, listingMeta } from '$lib/entities/schema-org';

  /**
   * Catalog adapter over `PaginatedListPage`: resolves a `catalogKey` to the
   * generic controller's presentation props via the model-driven `ENTITY_META`
   * registry. This is the *only* listing component coupled to the catalog —
   * the controller itself stays entity-agnostic, so a non-catalog list (users,
   * etc.) is a sibling adapter that supplies the same props directly, not a
   * fork of the controller.
   */
  let {
    catalogKey,
    subtitle,
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
    catalogKey: CatalogEntityKey;
    subtitle?: string;
    initial: { items: T[]; count: number };
    fetchPage: (page: number) => Promise<{ items: T[]; count: number }>;
    q: string;
    canCreate?: boolean;
    /** `'row'` (default) or `'card'` (a card grid, e.g. people). */
    layout?: 'row' | 'card';
    /** Committed extra URL query params beyond `q` (e.g. systems' `{ manufacturer }`). */
    extraParams?: Record<string, string>;
    /** Control beside the search box (e.g. a manufacturer `<select>`); receives `setExtra`. */
    extraFilter?: Snippet<[(extra: Record<string, string>) => void]>;
    headerSnippet?: Snippet;
    children: Snippet<[T]>;
  } = $props();

  let meta = $derived(ENTITY_META[catalogKey]);
  let listingCopy = $derived(listingMeta(catalogKey));
  // The listing description is the single source for both the visible subtitle
  // and the <meta>/JSON-LD description; an explicit `subtitle` prop overrides it.
  let subtitleText = $derived(subtitle ?? listingCopy.description);
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

<PaginatedListPage
  title={listingCopy.heading}
  subtitle={subtitleText}
  basePath={`/${meta.entity_type_plural}`}
  singularLabel={meta.label.toLowerCase()}
  singularTitle={meta.label}
  {initial}
  {fetchPage}
  {q}
  {canCreate}
  {layout}
  {extraParams}
  {extraFilter}
  {headerSnippet}
  {children}
/>
