<!-- @component The /games listing page: heterogeneous Title/Model cards with faceted filtering. -->
<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import FacetedCatalogListing from '$lib/components/pages/listing/FacetedCatalogListing.svelte';
  import GameFilterSidebar from './_components/GameFilterSidebar.svelte';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';
  import { filtersFromParams, filtersToParams } from '$lib/facet-engine';
  import { gameFilterChips } from './games-filter-chips';

  let { data } = $props();

  // Stable identity (defined once, not per render) so the shell's filters→URL
  // effect doesn't re-run on every load.
  const engine = { fromParams: filtersFromParams, toParams: filtersToParams };

  // Typed page fetcher: the `/api/games/` path literal is baked in here so the
  // response stays typed (`GameCardSchema`), then flows generically through
  // FacetedCatalogListing. Reuses the committed `data.query` for load-more.
  const fetchPage = (page: number) =>
    client
      .GET('/api/games/', { params: { query: { ...data.query, page } } })
      .then((r) => unwrapPage(r.data));
</script>

<FacetedCatalogListing
  catalogKey="title"
  {engine}
  Sidebar={GameFilterSidebar}
  chips={gameFilterChips}
  filterOptions={data.filter_options}
  queryCount={data.query_count}
  query={data.query}
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
>
  {#snippet children(game)}
    <GameCard
      entityType={game.entity_type}
      publicId={game.public_id}
      name={game.name}
      thumbnailUrl={game.thumbnail_url}
      manufacturerName={game.manufacturer?.name}
      year={game.year}
    />
  {/snippet}
</FacetedCatalogListing>
