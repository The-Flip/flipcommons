<script lang="ts">
  import client from '$lib/api/client';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/CatalogListRow.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/franchises/` path literal is baked in here so
  // the response stays typed (`FranchiseListItemSchema`), then flows generically
  // through CatalogListing. Reads the committed `q` at call time. Throws on an
  // error response rather than degrading to an empty page: a `{count: 0}` would
  // set the loader's `hasMore` false and silently, permanently halt infinite
  // scroll on a transient page-2 failure. Throwing routes it to the loader's
  // catch, which keeps `hasMore`/`nextPage` intact so the next scroll retries.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/franchises/', {
      params: { query: { q: data.q, page } },
    });
    if (!res.data) throw new Error('Failed to load franchises');
    return res.data;
  };
</script>

<CatalogListing
  catalogKey="franchise"
  subtitle="Licensed and original franchises featured in pinball."
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet children(franchise)}
    <CatalogListRow name={franchise.name} count={franchise.title_count} />
  {/snippet}
</CatalogListing>
