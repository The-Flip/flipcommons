<script lang="ts">
  import FacetedCatalogListing from './FacetedCatalogListing.svelte';
  import Sidebar from './FacetedCatalogListing.fixtureSidebar.svelte';
  import type { FilterChipSpec } from '$lib/components/collections/filters/ActiveFilterChips.svelte';
  import type { CatalogEntityKey } from '$lib/entities/entity-meta';
  import { parseParams, serializeParams, type ParamSpec } from '$lib/filters/params';

  type F = { query: string; foo: string | null };
  type O = { foo: { public_id: string; name: string; count: number }[] };
  type Item = { slug: string; name: string };
  type Q = { q?: string };

  let {
    catalogKey = 'manufacturer',
    initial,
    query = {},
    filterOptions = Promise.resolve<O | undefined>({ foo: [] }),
    queryCount = Promise.resolve<number | null | undefined>(null),
    fetchPage = () => Promise.resolve({ items: [], count: 0 }),
  }: {
    catalogKey?: CatalogEntityKey;
    initial: { items: Item[]; count: number };
    query?: Q;
    filterOptions?: Promise<O | undefined>;
    queryCount?: Promise<number | null | undefined>;
    fetchPage?: (page: number) => Promise<{ items: Item[]; count: number }>;
  } = $props();

  const params: Record<string, ParamSpec<F>> = {
    q: { get: (f) => f.query || null, set: (f, v) => (f.query = v) },
    foo: { get: (f) => f.foo, set: (f, v) => (f.foo = v) },
  };
  const engine = {
    parse: (sp: URLSearchParams): F => parseParams(sp, { query: '', foo: null }, params),
    serialize: (f: F) => serializeParams(f, params),
    canonical: (f: F) => serializeParams(f, params).toString(),
  };

  const chips = (f: F): FilterChipSpec[] =>
    f.foo ? [{ key: `foo:${f.foo}`, label: `Foo: ${f.foo}`, remove: () => (f.foo = null) }] : [];
</script>

<FacetedCatalogListing
  {catalogKey}
  {engine}
  {Sidebar}
  {chips}
  {filterOptions}
  {queryCount}
  {query}
  {initial}
  {fetchPage}
>
  {#snippet children(item)}
    <span>{item.name}</span>
  {/snippet}
</FacetedCatalogListing>
