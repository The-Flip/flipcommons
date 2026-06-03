<script lang="ts">
  import ChipGroup from '$lib/components/ui/ChipGroup.svelte';
  import SearchableSelect from './SearchableSelect.svelte';
  import YearRangeInput from './YearRangeInput.svelte';
  import {
    emptyMfrFilterState,
    hasActiveMfrFilters,
    type MfrFilterState,
  } from '$lib/manufacturer-facet-engine';
  import type { FacetOptionSchema, ManufacturerFilterOptionsSchema } from '$lib/api/schema';

  let {
    filterOptions,
    disabled = false,
    busy = false,
    filters = $bindable(),
  }: {
    /**
     * Server-computed option lists with live N-1 counts (public_id, name, count).
     * `undefined` while the facet stream is in flight on first/cold load — the
     * controls render disabled and empty until it arrives (see `streamed`).
     */
    filterOptions: ManufacturerFilterOptionsSchema | undefined;
    /** Disable every control (first/cold load, before any options have arrived). */
    disabled?: boolean;
    /** A refetch is in flight (sets `aria-busy` for screen readers; not visually disabled). */
    busy?: boolean;
    filters: MfrFilterState;
  } = $props();

  /** Backend `{public_id, name, count}` → the `{value, label, count}` the controls take. */
  function toOptions(opts: FacetOptionSchema[]): { value: string; label: string; count: number }[] {
    return opts.map((o) => ({ value: o.public_id, label: o.name, count: o.count }));
  }

  let locationOptions = $derived(filterOptions ? toOptions(filterOptions.location) : []);
  let personOptions = $derived(filterOptions ? toOptions(filterOptions.person) : []);
  let techGenOptions = $derived(filterOptions ? toOptions(filterOptions.tech_gen) : []);

  let anyActive = $derived(hasActiveMfrFilters(filters));

  function clearAll() {
    filters = emptyMfrFilterState();
  }
</script>

<aside class="sidebar" aria-busy={busy}>
  <div class="sidebar-header">
    <h2>Filters</h2>
    {#if anyActive}
      <button class="clear-all" {disabled} onclick={clearAll}>Clear all</button>
    {/if}
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Location"
      options={locationOptions}
      bind:selected={filters.location}
      {disabled}
      placeholder="Search locations..."
      emptyMessage="No locations match your other filters"
    />
  </div>

  <div class="filter-section">
    <span class="filter-label">Year</span>
    <YearRangeInput bind:min={filters.yearMin} bind:max={filters.yearMax} {disabled} />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Person"
      options={personOptions}
      bind:selected={filters.person}
      {disabled}
      placeholder="Search people..."
      emptyMessage="No people match your other filters"
    />
  </div>

  <div class="filter-section">
    <ChipGroup
      label="Tech generation"
      options={techGenOptions}
      bind:selected={filters.techGeneration}
      {disabled}
    />
  </div>
</aside>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--size-3);
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .sidebar-header h2 {
    font-size: var(--font-size-2);
    margin: 0;
  }

  .clear-all {
    background: none;
    border: none;
    color: var(--color-link);
    cursor: pointer;
    font-size: var(--font-size-0);
    font-family: var(--font-body);
    padding: 0;
  }

  .clear-all:hover:not(:disabled) {
    text-decoration: underline;
  }

  .clear-all:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .filter-section {
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }

  .filter-label {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }
</style>
