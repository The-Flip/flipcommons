<!-- @component One export-market line: a linked country, a plain-text region label ("Europe"), or the fixed unknown-market copy when the row has neither. -->
<script lang="ts">
  import { resolve } from '$app/paths';
  import type { ModelExportMarketView } from '$lib/entities/model-lineage';

  let { market }: { market: ModelExportMarketView } = $props();
</script>

{#if market.location}
  <a href={resolve('/locations/[...path]', { path: market.location.public_id })}
    >{market.location.name}</a
  >
{:else if market.label}
  {market.label}
{:else}
  <span class="unknown">Unknown market</span>
{/if}

<style>
  .unknown {
    color: var(--color-text-muted);
    font-style: italic;
  }
</style>
