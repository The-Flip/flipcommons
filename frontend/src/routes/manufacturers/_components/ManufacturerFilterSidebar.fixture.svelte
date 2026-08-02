<script lang="ts">
  import ManufacturerFilterSidebar from './ManufacturerFilterSidebar.svelte';
  import { emptyMfrFilterState, type MfrFilterState } from '$lib/filters/manufacturers';
  import type { ManufacturerFilterOptionsSchema } from '$lib/api/schema';

  const FILTER_OPTIONS: ManufacturerFilterOptionsSchema = {
    location: [
      { public_id: 'usa', name: 'USA', count: 2 },
      { public_id: 'italy', name: 'Italy', count: 1 },
    ],
    person: [
      { public_id: 'pat-lawlor', name: 'Pat Lawlor', count: 1 },
      { public_id: 'steve-ritchie', name: 'Steve Ritchie', count: 2 },
    ],
    technology_generation: [
      { public_id: 'solid-state', name: 'Solid State', count: 2 },
      { public_id: 'electromechanical', name: 'Electromechanical', count: 1 },
    ],
    year: { min: 1967, max: 2024 },
  };

  // `noOptions` simulates first/cold load (options still streaming) — passing
  // `filterOptions={undefined}` directly would hit the prop default, so use a flag.
  let {
    noOptions = false,
    disabled = false,
    busy = false,
    initialFilters,
  }: {
    noOptions?: boolean;
    disabled?: boolean;
    busy?: boolean;
    initialFilters?: MfrFilterState;
  } = $props();

  // Seed once from the prop via a closure so Svelte doesn't flag the initializer
  // as a non-reactive capture (state_referenced_locally) — the seed is intentional.
  function seedFilters(): MfrFilterState {
    return initialFilters ?? emptyMfrFilterState();
  }
  let filters = $state(seedFilters());
</script>

<ManufacturerFilterSidebar
  filterOptions={noOptions ? undefined : FILTER_OPTIONS}
  {disabled}
  {busy}
  bind:filters
/>
