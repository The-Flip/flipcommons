<script lang="ts">
  import client from '$lib/api/client';
  import { createAsyncLoader } from '$lib/async-loader.svelte';
  import TaxonomyListPage from '$lib/components/TaxonomyListPage.svelte';
  import type { SystemListItemSchema } from '$lib/api/schema';

  type SystemRow = SystemListItemSchema;

  const systems = createAsyncLoader(async () => {
    const { data } = await client.GET('/api/systems/all/');
    return data ?? [];
  }, []);

  let manufacturerFilter = $state<string>('');

  let manufacturerOptions = $derived.by(() => {
    const seen: Record<string, string> = {};
    for (const s of systems.data) {
      if (!(s.manufacturer.public_id in seen)) {
        seen[s.manufacturer.public_id] = s.manufacturer.name;
      }
    }
    return Object.entries(seen)
      .map(([publicId, name]) => ({ slug: publicId, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  });

  function filterByManufacturer(s: SystemRow): boolean {
    if (!manufacturerFilter) return true;
    return s.manufacturer.public_id === manufacturerFilter;
  }
</script>

<svelte:head>
  <link rel="preload" as="fetch" href="/api/systems/all/" crossorigin="anonymous" />
</svelte:head>

<TaxonomyListPage
  catalogKey="system"
  items={systems.data}
  loading={systems.loading}
  error={systems.error}
  canCreate
  filterFn={filterByManufacturer}
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

  {#snippet filters()}
    {#if manufacturerOptions.length > 1}
      <div class="mfr-filter">
        <label for="mfr-filter-select">Manufacturer</label>
        <select id="mfr-filter-select" bind:value={manufacturerFilter}>
          <option value="">All manufacturers</option>
          {#each manufacturerOptions as opt (opt.slug)}
            <option value={opt.slug}>{opt.name}</option>
          {/each}
        </select>
      </div>
    {/if}
  {/snippet}

  {#snippet rowSnippet(system)}
    <span class="system-name">{system.name}</span>
    <span class="system-meta">
      {#if system.manufacturer}
        <span class="manufacturer">{system.manufacturer.name}</span>
      {/if}
      <span class="count">
        {system.model_count} model{system.model_count === 1 ? '' : 's'}
      </span>
    </span>
  {/snippet}
</TaxonomyListPage>

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

  .mfr-filter select {
    font: inherit;
    padding: var(--size-1) var(--size-2);
  }

  .system-name {
    font-size: var(--font-size-2);
    color: var(--color-text);
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
