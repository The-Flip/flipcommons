<script lang="ts">
  import ManufacturerFilterSidebar from './ManufacturerFilterSidebar.svelte';
  import { emptyMfrFilterState } from '$lib/manufacturer-facet-engine';
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
    tech_gen: [
      { public_id: 'solid-state', name: 'Solid State', count: 2 },
      { public_id: 'electromechanical', name: 'Electromechanical', count: 1 },
    ],
    year: { min: 1967, max: 2024 },
  };

  let filters = $state(emptyMfrFilterState());
</script>

<ManufacturerFilterSidebar filterOptions={FILTER_OPTIONS} bind:filters />
