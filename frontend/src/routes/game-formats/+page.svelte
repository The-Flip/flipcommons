<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import CatalogListRow from '$lib/components/collections/list/CatalogListRow.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/game-formats/` path literal is baked in here so
  // the response stays typed, then flows generically through CatalogListing.
  // Reads the committed `q` at call time.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/game-formats/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="game-format"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet headerSnippet()}
    <p class="overview">
      A <strong>game format</strong> is the broad category of device a machine belongs to.
    </p>
    <p class="overview">
      <a href="/game-formats/pinball">Pinball</a> is the reason this site exists. Pinball descends
      directly from <a href="/game-formats/bagatelle">bagatelle</a>, the flipperless
      plunger-and-gravity ancestor that established the basic form.
    </p>
    <p class="overview">
      Most of the formats occupy different niches on the coin-op route, sharing manufacturers,
      operators, and distribution with pinball. Over the years, big manufacturers like
      <a href="/manufacturers/williams">Williams</a> and
      <a href="/manufacturers/chicago-coin">Chicago Coin</a>
      built most of them.
    </p>
  {/snippet}

  {#snippet children(format)}
    <CatalogListRow name={format.name} count={format.title_count} />
  {/snippet}
</CatalogListing>

<style>
  .overview {
    font-size: var(--font-size-2);
    color: var(--color-text-muted);
    margin-top: var(--size-2);
    max-width: 42rem;
    line-height: 1.5;
  }

  .overview a {
    color: var(--color-link);
  }
</style>
