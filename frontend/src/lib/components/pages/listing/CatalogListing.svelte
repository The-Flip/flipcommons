<script lang="ts" generics="T extends { slug: string }">
  import type { Snippet } from 'svelte';
  import PaginatedListPage from './PaginatedListPage.svelte';
  import { ENTITY_META, type CatalogEntityKey } from '$lib/entities/entity-meta';

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
    headerSnippet,
    children,
  }: {
    catalogKey: CatalogEntityKey;
    subtitle?: string;
    initial: { items: T[]; count: number };
    fetchPage: (page: number) => Promise<{ items: T[]; count: number }>;
    q: string;
    canCreate?: boolean;
    headerSnippet?: Snippet;
    children: Snippet<[T]>;
  } = $props();

  let meta = $derived(ENTITY_META[catalogKey]);
</script>

<PaginatedListPage
  title={meta.label_plural}
  {subtitle}
  basePath={`/${meta.entity_type_plural}`}
  singularLabel={meta.label.toLowerCase()}
  singularTitle={meta.label}
  {initial}
  {fetchPage}
  {q}
  {canCreate}
  {headerSnippet}
  {children}
/>
