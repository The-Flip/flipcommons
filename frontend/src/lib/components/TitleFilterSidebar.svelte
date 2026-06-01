<script lang="ts">
  import ChipGroup from './ChipGroup.svelte';
  import SearchableSelect from './SearchableSelect.svelte';
  import YearRangeInput from './YearRangeInput.svelte';
  import { emptyFilterState, hasActiveFilters, type FilterState } from '$lib/facet-engine';
  import type { FacetOptionSchema, FilterOptionsSchema } from '$lib/api/schema';

  let {
    filterOptions,
    filters = $bindable(),
  }: {
    /** Server-computed option lists with live N-1 counts (public_id, name, count). */
    filterOptions: FilterOptionsSchema;
    filters: FilterState;
  } = $props();

  /** Backend `{public_id, name, count}` → the `{value, label, count}` the controls take. */
  function toOptions(opts: FacetOptionSchema[]): { value: string; label: string; count: number }[] {
    return opts.map((o) => ({ value: o.public_id, label: o.name, count: o.count }));
  }

  let manufacturerOptions = $derived(toOptions(filterOptions.manufacturer));
  let personOptions = $derived(toOptions(filterOptions.person));
  let themeOptions = $derived(toOptions(filterOptions.theme));
  let featureOptions = $derived(toOptions(filterOptions.feature));
  let rewardTypeOptions = $derived(toOptions(filterOptions.reward_type));
  let techGenOptions = $derived(toOptions(filterOptions.tech_gen));
  let displayTypeOptions = $derived(toOptions(filterOptions.display_type));
  let systemOptions = $derived(toOptions(filterOptions.system));
  let franchiseOptions = $derived(toOptions(filterOptions.franchise));
  let seriesOptions = $derived(toOptions(filterOptions.series));

  // Player count: server returns {value, count} buckets; ChipGroup wants string
  // values, and `filters.playerCount` is number|null. The "6+" bucket renders
  // under value 6.
  let playerCountChipOptions = $derived(
    filterOptions.player_count.map((o) => ({
      value: String(o.value),
      label: o.value >= 6 ? '6+' : String(o.value),
      count: o.count,
    })),
  );
  let playerCountValue = $derived(filters.playerCount != null ? String(filters.playerCount) : null);

  function setPlayerCount(value: string | null) {
    filters.playerCount = value ? Number(value) : null;
  }

  let anyActive = $derived(hasActiveFilters(filters));

  function clearAll() {
    filters = emptyFilterState();
  }
</script>

<aside class="sidebar">
  <div class="sidebar-header">
    <h2>Filters</h2>
    {#if anyActive}
      <button class="clear-all" onclick={clearAll}>Clear all</button>
    {/if}
  </div>

  <div class="filter-section">
    <span class="filter-label">Year</span>
    <YearRangeInput bind:min={filters.yearMin} bind:max={filters.yearMax} />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Manufacturer"
      options={manufacturerOptions}
      bind:selected={filters.manufacturer}
      placeholder="Search manufacturers..."
      emptyMessage="No manufacturers match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Person"
      options={personOptions}
      bind:selected={filters.person}
      placeholder="Search people..."
      emptyMessage="No people match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Theme"
      options={themeOptions}
      bind:selected={filters.themes}
      multi
      placeholder="Search themes..."
      emptyMessage="No themes match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Feature"
      options={featureOptions}
      bind:selected={filters.features}
      multi
      placeholder="Search features..."
      emptyMessage="No features match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Reward Type"
      options={rewardTypeOptions}
      bind:selected={filters.rewardTypes}
      multi
      placeholder="Search reward types..."
      emptyMessage="No reward types match your other filters"
    />
  </div>

  <div class="filter-section">
    <ChipGroup
      label="Tech generation"
      options={techGenOptions}
      bind:selected={filters.techGeneration}
    />
  </div>

  <div class="filter-section">
    <ChipGroup
      label="Display type"
      options={displayTypeOptions}
      bind:selected={filters.displayType}
    />
  </div>

  <div class="filter-section">
    <ChipGroup
      label="Player count"
      options={playerCountChipOptions}
      selected={playerCountValue}
      onchange={setPlayerCount}
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="System"
      options={systemOptions}
      bind:selected={filters.system}
      placeholder="Search systems..."
      emptyMessage="No systems match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Franchise"
      options={franchiseOptions}
      bind:selected={filters.franchise}
      placeholder="Search franchises..."
      emptyMessage="No franchises match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Series"
      options={seriesOptions}
      bind:selected={filters.series}
      placeholder="Search series..."
      emptyMessage="No series match your other filters"
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

  .clear-all:hover {
    text-decoration: underline;
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
