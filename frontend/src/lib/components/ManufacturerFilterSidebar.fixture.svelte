<script lang="ts">
  import ManufacturerFilterSidebar from './ManufacturerFilterSidebar.svelte';
  import { emptyMfrFilterState, type FacetedManufacturer } from '$lib/manufacturer-facet-engine';

  const MANUFACTURERS: FacetedManufacturer[] = [
    {
      name: 'Stern Pinball',
      slug: 'stern-pinball',
      model_count: 30,
      locations: [{ public_id: 'usa', name: 'USA' }],
      year_min: 1977,
      year_max: 2024,
      persons: [{ public_id: 'steve-ritchie', name: 'Steve Ritchie' }],
      tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
    },
    {
      name: 'Williams Electronics',
      slug: 'williams-electronics',
      model_count: 40,
      locations: [{ public_id: 'usa', name: 'USA' }],
      year_min: 1967,
      year_max: 2000,
      persons: [{ public_id: 'pat-lawlor', name: 'Pat Lawlor' }],
      tech_generations: [{ public_id: 'solid-state', name: 'Solid State' }],
    },
    {
      name: 'Zaccaria',
      slug: 'zaccaria',
      model_count: 18,
      locations: [{ public_id: 'italy', name: 'Italy' }],
      year_min: 1974,
      year_max: 1987,
      persons: [{ public_id: 'renato-digioia', name: 'Renato Di Gioia' }],
      tech_generations: [{ public_id: 'electromechanical', name: 'Electromechanical' }],
    },
  ];

  let filters = $state(emptyMfrFilterState());
</script>

<ManufacturerFilterSidebar allManufacturers={MANUFACTURERS} bind:filters />
