<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/list/CatalogListRow.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/themes/` path literal is baked in here so the
  // response stays typed, then flows generically through CatalogListing. Reads
  // the committed `q` at call time. The hierarchical title-count rollup is
  // resolved server-side; the listing renders a flat name+count row.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/themes/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="theme"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet children(theme)}
    <CatalogListRow name={theme.name} count={theme.title_count} />
  {/snippet}
</CatalogListing>
