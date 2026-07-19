<!-- @component Renders every model↔model lineage relation present on a model as `<h3>` + link-list groups, then the model's relationship-edge sections (copy / conversion / kit, outbound then inbound), then its export-markets group. The mobile presentation (the sidebar renders its own via `SidebarSection`); shared by the model page's Related Models accordion and the single-model title page. -->
<script lang="ts">
  import ExportMarketLine from './ExportMarketLine.svelte';
  import ModelEdgeTargetList from './ModelEdgeTargetList.svelte';
  import ModelLineageLinkList from './ModelLineageLinkList.svelte';
  import {
    modelEdgeSections,
    modelExportMarketSection,
    modelLineageSections,
  } from '$lib/entities/model-lineage';
  import type { ModelDetailSchema } from '$lib/api/schema';

  let { model }: { model: ModelDetailSchema } = $props();

  let exportMarkets = $derived(modelExportMarketSection(model));
</script>

{#each modelLineageSections(model) as { relation, links } (relation.key)}
  <div class="relationship-group">
    <h3>{relation.heading}</h3>
    {#if relation.note}
      <p class="note">{relation.note}</p>
    {/if}
    <ModelLineageLinkList {links} />
  </div>
{/each}

{#each modelEdgeSections(model) as { key, heading, note, targets } (key)}
  <div class="relationship-group">
    <h3>{heading}</h3>
    <p class="note">{note}</p>
    <ModelEdgeTargetList {targets} />
  </div>
{/each}

{#if exportMarkets}
  <div class="relationship-group">
    <h3>{exportMarkets.heading}</h3>
    <p class="note">{exportMarkets.note}</p>
    <ul class="markets">
      {#each exportMarkets.markets as market (market.location?.public_id ?? market.label)}
        <li><ExportMarketLine {market} /></li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .relationship-group {
    margin-bottom: var(--size-3);
  }

  .relationship-group:last-child {
    margin-bottom: 0;
  }

  .relationship-group h3 {
    font-size: var(--font-size-0);
    font-weight: 600;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 var(--size-1);
  }

  .note {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-1);
  }

  .markets {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .markets li {
    padding: var(--size-1) 0;
    font-size: var(--font-size-0);
  }
</style>
