<script module lang="ts">
  /** One active-filter chip: a label plus the action that clears that filter. */
  export interface FilterChipSpec {
    /** Stable key for the keyed `{#each}` (e.g. "themes:sci-fi"). */
    key: string;
    /** Human-readable label shown in the chip. */
    label: string;
    /** Clears the filter this chip represents. */
    remove: () => void;
  }
</script>

<script lang="ts">
  import FilterChip from './FilterChip.svelte';

  let { chips }: { chips: FilterChipSpec[] } = $props();
</script>

{#if chips.length > 0}
  <div class="active-filters" role="list" aria-label="Active filters">
    {#each chips as chip (chip.key)}
      <FilterChip label={chip.label} onRemove={chip.remove} />
    {/each}
  </div>
{/if}

<style>
  .active-filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-1);
    margin-bottom: var(--size-3);
  }
</style>
