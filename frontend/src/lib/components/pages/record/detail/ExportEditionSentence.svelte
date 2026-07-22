<!-- @component The export-edition sentence — "This model is the export version of X, built for export to Y and Z." Each half is dropped when its fact is unknown, down to a bare "built for export" for a model whose only market row names no market. Shared by the mobile lineage groups and the desktop sidebar. -->
<script lang="ts">
  import RelatedModelLink from './RelatedModelLink.svelte';
  import { resolve } from '$app/paths';
  import type { ModelExportEditionSection } from '$lib/entities/model-lineage';

  let { section }: { section: ModelExportEditionSection } = $props();
</script>

{#snippet markets()}{#each section.markets as market, i (market.location?.public_id ?? market.label)}{#if i > 0}{i ===
      section.markets.length - 1
        ? ' and '
        : ', '}{/if}{#if market.location}<a
        href={resolve('/locations/[...path]', { path: market.location.public_id })}
        >{market.location.name}</a
      >{:else}{market.label}{/if}{/each}{/snippet}

<p class="sentence">
  {#if section.original}This model is the export version of <RelatedModelLink
      link={section.original}
    />{#if section.markets.length > 0}, built for export to {@render markets()}{/if}.
  {:else if section.markets.length > 0}This model was built for export to {@render markets()}.
  {:else}This model was built for export.
  {/if}
</p>

<style>
  .sentence {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0;
  }
</style>
