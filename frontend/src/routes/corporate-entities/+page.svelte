<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';
  import { formatYearRange } from '$lib/utils';

  let { data } = $props();

  // Typed page fetcher: the `/api/corporate-entities/` path literal is baked in
  // here so the response stays typed, then flows generically through
  // CatalogListing. Reads the committed `q` at call time.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/corporate-entities/', {
      params: { query: { q: data.q, page } },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="corporate-entity"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  canCreate
>
  {#snippet children(entity)}
    <span class="entity-name">{entity.name}</span>
    <span class="entity-meta">
      <span class="manufacturer">{entity.manufacturer.name}</span>
      {#if formatYearRange(entity.year_start, entity.year_end)}
        <span class="years">{formatYearRange(entity.year_start, entity.year_end)}</span>
      {/if}
      <span class="count">
        {entity.model_count} model{entity.model_count === 1 ? '' : 's'}
      </span>
    </span>
  {/snippet}
</CatalogListing>

<style>
  .entity-name {
    font-size: var(--font-size-2);
    /* `inherit` so the name picks up the row's link color on hover (the meta
       spans set their own muted color and stay put), matching the plain rows. */
    color: inherit;
    font-weight: 500;
  }

  .entity-meta {
    display: flex;
    gap: var(--size-4);
    flex-shrink: 0;
    align-items: baseline;
  }

  .manufacturer {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  .years {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  .count {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    min-width: 6rem;
    text-align: right;
  }
</style>
