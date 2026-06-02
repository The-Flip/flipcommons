<script lang="ts">
  import CatalogListing from './CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/CatalogListRow.svelte';

  type Row = { slug: string; name: string; title_count: number };

  let {
    initial,
    q = '',
    canCreate = false,
    fetchPage = () => Promise.resolve({ items: [], count: 0 }),
  }: {
    initial: { items: Row[]; count: number };
    q?: string;
    canCreate?: boolean;
    fetchPage?: (page: number) => Promise<{ items: Row[]; count: number }>;
  } = $props();
</script>

<CatalogListing catalogKey="franchise" {initial} {q} {fetchPage} {canCreate}>
  {#snippet children(franchise)}
    <CatalogListRow name={franchise.name} count={franchise.title_count} />
  {/snippet}
</CatalogListing>
