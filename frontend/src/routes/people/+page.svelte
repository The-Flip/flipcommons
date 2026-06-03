<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import PersonCard from '$lib/components/collections/cards/PersonCard.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/people/` path literal is baked in here so the
  // response stays typed (`PersonCardSchema`), then flows generically through
  // CatalogListing's card layout. Reads the committed `q` at call time.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/people/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="person"
  layout="card"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet children(person)}
    <PersonCard
      slug={person.slug}
      name={person.name}
      thumbnailUrl={person.thumbnail_url}
      creditCount={person.credit_count}
    />
  {/snippet}
</CatalogListing>
