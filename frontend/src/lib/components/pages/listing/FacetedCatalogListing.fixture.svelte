<script lang="ts">
  import FacetedCatalogListing from './FacetedCatalogListing.svelte';
  import Sidebar from './FacetedCatalogListing.fixtureSidebar.svelte';
  import type { FilterChipSpec } from '$lib/components/ActiveFilterChips.svelte';

  type F = { query: string; foo: string | null };
  type O = { foo: { public_id: string; name: string; count: number }[] };
  type Item = { slug: string; name: string };
  type Q = { q?: string };

  let {
    initial,
    query = {},
    filterOptions = Promise.resolve<O | undefined>({ foo: [] }),
    queryCount = Promise.resolve<number | null | undefined>(null),
    fetchPage = () => Promise.resolve({ items: [], count: 0 }),
  }: {
    initial: { items: Item[]; count: number };
    query?: Q;
    filterOptions?: Promise<O | undefined>;
    queryCount?: Promise<number | null | undefined>;
    fetchPage?: (page: number) => Promise<{ items: Item[]; count: number }>;
  } = $props();

  const engine = {
    fromParams: (sp: URLSearchParams): F => ({ query: sp.get('q') ?? '', foo: sp.get('foo') }),
    toParams: (f: F, sp: URLSearchParams) => {
      if (f.query) sp.set('q', f.query);
      if (f.foo) sp.set('foo', f.foo);
      return sp;
    },
  };

  const chips = (f: F): FilterChipSpec[] =>
    f.foo ? [{ key: `foo:${f.foo}`, label: `Foo: ${f.foo}`, remove: () => (f.foo = null) }] : [];
</script>

<FacetedCatalogListing
  catalogKey="manufacturer"
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
