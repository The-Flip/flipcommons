<script lang="ts">
  import client from '$lib/api/client';
  import { unwrapPage } from '$lib/paginated-loader.svelte';
  import CatalogListing from '$lib/components/pages/listing/CatalogListing.svelte';

  let { data } = $props();

  // Typed page fetcher: the `/api/systems/` path literal is baked in here so the
  // response stays typed (`SystemListItemSchema`), then flows generically
  // through CatalogListing. Threads the committed `q` and `manufacturer` filter.
  const fetchPage = async (page: number) => {
    const res = await client.GET('/api/systems/', {
      params: {
        query: { q: data.q, manufacturer: data.manufacturer || undefined, page },
      },
    });
    return unwrapPage(res.data);
  };
</script>

<CatalogListing
  catalogKey="system"
  initial={{ items: data.items, count: data.count }}
  {fetchPage}
  q={data.q}
  extraParams={{ manufacturer: data.manufacturer }}
  canCreate
>
  {#snippet headerSnippet()}
    <p class="overview">
      A <strong>system</strong> is the electronic hardware platform — the CPU board, driver board,
      and firmware — that a pinball machine runs on. Most manufacturers produce a succession of
      systems as technology evolves: <a href="/manufacturers/williams">Williams</a> moved from
      <a href="/systems/williams-system-3">System 3</a> through
      <a href="/systems/williams-system-11">System 11</a> and eventually to
      <a href="/systems/wpc-95">WPC-95</a>, while
      <a href="/manufacturers/stern-pinball">Stern Pinball</a> currently ships on
      <a href="/systems/stern-spike-2">SPIKE 2</a>. A single title can appear on multiple systems
      when it is remade years later — <a href="/manufacturers/williams">Williams</a>' original
      <a href="/titles/medieval-madness"><em>Medieval Madness</em></a> runs on
      <a href="/systems/wpc-95">WPC-95</a>, while
      <a href="/manufacturers/chicago-gaming">Chicago Gaming</a>'s remake runs on
      <a href="/systems/cgc-pinball-controller-os">CGC Pinball Controller/OS</a>.
    </p>
  {/snippet}

  {#snippet extraFilter(setExtra)}
    {#if data.manufacturerOptions.length > 1}
      <div class="mfr-filter">
        <label for="mfr-filter-select">Manufacturer</label>
        <select
          id="mfr-filter-select"
          value={data.manufacturer}
          onchange={(e) => setExtra({ manufacturer: e.currentTarget.value })}
        >
          <option value="">All manufacturers</option>
          {#each data.manufacturerOptions as opt (opt.value)}
            <option value={opt.value}>{opt.name}</option>
          {/each}
        </select>
      </div>
    {/if}
  {/snippet}

  {#snippet children(system)}
    <span class="system-name">{system.name}</span>
    <span class="system-meta">
      <span class="manufacturer">{system.manufacturer.name}</span>
      <span class="count">
        {system.model_count} model{system.model_count === 1 ? '' : 's'}
      </span>
    </span>
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

  .mfr-filter {
    display: flex;
    align-items: baseline;
    gap: var(--size-2);
    padding: var(--size-2) 0 var(--size-3);
  }

  .mfr-filter label {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
  }

  .system-name {
    font-size: var(--font-size-2);
    /* `inherit` so the name picks up the row's link color on hover (the meta
       spans set their own muted color and stay put), matching the plain rows. */
    color: inherit;
    font-weight: 500;
  }

  .system-meta {
    display: flex;
    gap: var(--size-4);
    flex-shrink: 0;
  }

  .manufacturer {
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
