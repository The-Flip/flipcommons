<!-- @component Filter sidebar for the /games listing: every surfaced facet control. -->
<script lang="ts">
  import ChipGroup from '$lib/components/ui/ChipGroup.svelte';
  import SearchableSelect from '$lib/components/input/SearchableSelect.svelte';
  import YearRangeInput from '$lib/components/input/YearRangeInput.svelte';
  import {
    UNCLASSIFIED,
    UNCLASSIFIED_LABEL,
    emptyFilterState,
    hasActiveFilters,
    presetValues,
    sparseSelection,
    type FilterState,
    type SparseField,
  } from '$lib/filters/games';
  import type { FacetOptionSchema, GameFilterOptionsSchema } from '$lib/api/schema';
  import { edgeFilterLabel } from '$lib/entities/relationship-phrase';

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
    filterOptions: GameFilterOptionsSchema | undefined;
    /** Disable every control (first/cold load, before any options have arrived). */
    disabled?: boolean;
    /** A refetch is in flight (sets `aria-busy` for screen readers; not visually disabled). */
    busy?: boolean;
    filters: FilterState;
  } = $props();

  /** Backend `{public_id, name, count}` → the `{value, label, count}` the controls take. */
  function toOptions(opts: FacetOptionSchema[]): { value: string; label: string; count: number }[] {
    return opts.map((o) => ({ value: o.public_id, label: o.name, count: o.count }));
  }

  let manufacturerOptions = $derived(filterOptions ? toOptions(filterOptions.manufacturer) : []);
  let personOptions = $derived(filterOptions ? toOptions(filterOptions.person) : []);
  let themeOptions = $derived(filterOptions ? toOptions(filterOptions.theme) : []);
  let featureOptions = $derived(filterOptions ? toOptions(filterOptions.gameplay_feature) : []);
  let rewardTypeOptions = $derived(filterOptions ? toOptions(filterOptions.reward_type) : []);
  // Edge options arrive named by wire value; the labels are the relationship
  // vocabulary's, resolved client-side.
  let edgeOptions = $derived(
    filterOptions
      ? filterOptions.edge.map((o) => ({
          value: o.public_id,
          label: edgeFilterLabel(o.public_id),
          count: o.count,
        }))
      : [],
  );
  // The sparse dimensions: single-select controls over multi-value state,
  // reading through sparseSelection and writing through presetValues. A lone
  // `unclassified` selection needs its option appended client-side — it is
  // never a payload option, and the input resolves its label from `options`.
  let gameFormatSelection = $derived(sparseSelection('gameFormats', filters.gameFormats));
  let productionStatusSelection = $derived(
    sparseSelection('productionStatuses', filters.productionStatuses),
  );
  let cabinetSelection = $derived(sparseSelection('cabinets', filters.cabinets));

  function sparseOptions(
    opts: FacetOptionSchema[] | undefined,
    selection: string | null,
  ): { value: string; label: string; count?: number }[] {
    const options: { value: string; label: string; count?: number }[] = opts ? toOptions(opts) : [];
    if (selection === UNCLASSIFIED) {
      options.push({ value: UNCLASSIFIED, label: UNCLASSIFIED_LABEL });
    }
    return options;
  }

  let gameFormatOptions = $derived(sparseOptions(filterOptions?.game_format, gameFormatSelection));
  let productionStatusOptions = $derived(
    sparseOptions(filterOptions?.production_status, productionStatusSelection),
  );
  let cabinetOptions = $derived(sparseOptions(filterOptions?.cabinet, cabinetSelection));

  function setSparse(field: SparseField, value: string | null) {
    filters[field] = value == null ? [] : presetValues(field, value);
  }

  let techGenOptions = $derived(
    filterOptions ? toOptions(filterOptions.technology_generation) : [],
  );
  let displayTypeOptions = $derived(filterOptions ? toOptions(filterOptions.display_type) : []);
  let systemOptions = $derived(filterOptions ? toOptions(filterOptions.system) : []);
  let franchiseOptions = $derived(filterOptions ? toOptions(filterOptions.franchise) : []);
  let seriesOptions = $derived(filterOptions ? toOptions(filterOptions.series) : []);

  // Player count: server returns {value, count} buckets; ChipGroup wants string
  // values, and `filters.playerCount` is number|null. The "6+" bucket renders
  // under value 6. Guarded for the undefined-options window like the others —
  // this builds its own buckets (not via `toOptions`), so it needs its own guard.
  let playerCountChipOptions = $derived(
    filterOptions
      ? filterOptions.player_count.map((o) => ({
          value: String(o.value),
          label: o.value >= 6 ? '6+' : String(o.value),
          count: o.count,
        }))
      : [],
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

<aside class="sidebar" aria-busy={busy}>
  <div class="sidebar-header">
    <h2>Filters</h2>
    {#if anyActive}
      <button class="clear-all" {disabled} onclick={clearAll}>Clear all</button>
    {/if}
  </div>

  <div class="filter-section">
    <span class="filter-label">Year</span>
    <YearRangeInput bind:min={filters.yearMin} bind:max={filters.yearMax} {disabled} />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Manufacturer"
      options={manufacturerOptions}
      bind:selected={filters.manufacturer}
      {disabled}
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
      {disabled}
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
      {disabled}
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
      {disabled}
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
      {disabled}
      placeholder="Search reward types..."
      emptyMessage="No reward types match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Relationship"
      options={edgeOptions}
      bind:selected={filters.edges}
      multi
      {disabled}
      placeholder="Search relationships..."
      emptyMessage="No relationships match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Game format"
      options={gameFormatOptions}
      bind:selected={() => gameFormatSelection, (v) => setSparse('gameFormats', v)}
      {disabled}
      placeholder="Search game formats..."
      emptyMessage="No game formats match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Production status"
      options={productionStatusOptions}
      bind:selected={() => productionStatusSelection, (v) => setSparse('productionStatuses', v)}
      {disabled}
      placeholder="Search production statuses..."
      emptyMessage="No production statuses match your other filters"
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="Cabinet"
      options={cabinetOptions}
      bind:selected={() => cabinetSelection, (v) => setSparse('cabinets', v)}
      {disabled}
      placeholder="Search cabinets..."
      emptyMessage="No cabinets match your other filters"
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

  <div class="filter-section">
    <ChipGroup
      label="Display type"
      options={displayTypeOptions}
      bind:selected={filters.displayType}
      {disabled}
    />
  </div>

  <div class="filter-section">
    <ChipGroup
      label="Player count"
      options={playerCountChipOptions}
      selected={playerCountValue}
      {disabled}
      onchange={setPlayerCount}
    />
  </div>

  <div class="filter-section">
    <SearchableSelect
      compact
      label="System"
      options={systemOptions}
      bind:selected={filters.system}
      {disabled}
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
      {disabled}
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
      {disabled}
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
