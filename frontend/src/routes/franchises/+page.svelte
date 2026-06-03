<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/CatalogListRow.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/franchises/` path literal is baked in here so
  // the response stays typed (`FranchiseListItemSchema`), then flows generically
  // through CatalogListing. Reads the committed `q` at call time. `unwrapPage`
  // throws on an error response rather than degrading to an empty page, so a
  // transient page-2 failure doesn't silently halt infinite scroll.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/franchises/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="franchise"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet children(franchise)}
    <CatalogListRow name={franchise.name} count={franchise.title_count} />
  {/snippet}
</CatalogListing>
