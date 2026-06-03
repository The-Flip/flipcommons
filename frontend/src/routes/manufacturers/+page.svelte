<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import FacetedCatalogListing from '$lib/components/pages/listing/FacetedCatalogListing.svelte';
  import ManufacturerFilterSidebar from '$lib/components/ManufacturerFilterSidebar.svelte';
  import ManufacturerCard from '$lib/components/collections/cards/ManufacturerCard.svelte';
  import { mfrFiltersFromParams, mfrFiltersToParams } from '$lib/manufacturer-facet-engine';
  import { manufacturerFilterChips } from './manufacturer-filter-chips';

  let { data } = $props();

  // Stable identity (defined once, not per render) so the shell's filters→URL
  // effect doesn't re-run on every load.
  const engine = { fromParams: mfrFiltersFromParams, toParams: mfrFiltersToParams };

  // Typed page fetcher: the `/api/manufacturers/` path literal is baked in here so
  // the response stays typed (`ManufacturerCardSchema`), then flows generically
  // through FacetedCatalogListing. Reuses the committed `data.query` for load-more.
  const fetchPage = (page: number) =>
    client
      .GET('/api/manufacturers/', { params: { query: { ...data.query, page } } })
      .then((r) => unwrapPage(r.data));
</script>

<FacetedCatalogListing
  catalogKey="manufacturer"
  {engine}
  Sidebar={ManufacturerFilterSidebar}
  chips={manufacturerFilterChips}
  filterOptions={data.filter_options}
  queryCount={data.query_count}
  query={data.query}
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
>
  {#snippet children(mfr)}
    <ManufacturerCard
      slug={mfr.slug}
      name={mfr.name}
      thumbnailUrl={mfr.thumbnail_url}
      modelCount={mfr.model_count}
    />
  {/snippet}
</FacetedCatalogListing>
