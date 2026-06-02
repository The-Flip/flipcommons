<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/CatalogListRow.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/series/` path literal is baked in here so the
  // response stays typed, then flows generically through CatalogListing. Reads
  // the committed `q` at call time.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/series/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="series"
  subtitle="Pinball titles sharing an original, non-licensed lineage."
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet children(series)}
    <CatalogListRow name={series.name} count={series.title_count} />
  {/snippet}
</CatalogListing>
