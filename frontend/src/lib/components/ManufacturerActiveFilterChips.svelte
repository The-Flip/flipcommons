<script lang="ts">
  import {
    getMfrActiveFilterLabels,
    type FacetedManufacturer,
    type MfrActiveFilterLabel,
    type MfrFilterState,
  } from '$lib/manufacturer-facet-engine';
  import ActiveFilterChips, { type FilterChipSpec } from '$lib/components/ActiveFilterChips.svelte';

  let {
    filters = $bindable(),
    allManufacturers,
  }: {
    filters: MfrFilterState;
    allManufacturers: FacetedManufacturer[];
  } = $props();

  function removeFilter(label: MfrActiveFilterLabel) {
    switch (label.field) {
      case 'yearMin':
      case 'yearMax':
        filters.yearMin = null;
        filters.yearMax = null;
        break;
      case 'location':
        filters.location = null;
        break;
      case 'person':
        filters.person = null;
        break;
      case 'techGeneration':
        filters.techGeneration = null;
        break;
      case 'query':
        filters.query = '';
        break;
      default:
        // Compile error if a new MfrFilterState field gains a chip but isn't
        // handled here, instead of silently no-op-ing at runtime.
        label.field satisfies never;
    }
  }

  let chips = $derived(
    getMfrActiveFilterLabels(filters, allManufacturers).map(
      (label): FilterChipSpec => ({
        key: label.key,
        label: label.label,
        remove: () => removeFilter(label),
      }),
    ),
  );
</script>

<ActiveFilterChips {chips} />
