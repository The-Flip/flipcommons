import type { MfrFilterState } from '$lib/manufacturer-facet-engine';
import type { FacetOptionSchema, ManufacturerFilterOptionsSchema } from '$lib/api/schema';
import type { FilterChipSpec } from '$lib/components/ActiveFilterChips.svelte';

/**
 * Build the active-filter chips for /manufacturers from the current filter state.
 *
 * `options` are the streamed facet lists, used only to resolve public_id → display
 * name; the chips' `remove` closures mutate the passed `filters` object (the page's
 * bindable `$state`), so clicking a chip clears that filter reactively. Pure and
 * component-free so the chip set can be unit-tested directly. Mirrors
 * `titles-filter-chips`; all manufacturer facets are single-select plus a year range.
 */
export function manufacturerFilterChips(
  filters: MfrFilterState,
  options: ManufacturerFilterOptionsSchema,
): FilterChipSpec[] {
  const chips: FilterChipSpec[] = [];
  const nameOf = (opts: FacetOptionSchema[], id: string): string =>
    opts.find((o) => o.public_id === id)?.name ?? id;

  const single = (
    value: string | null,
    field: 'location' | 'person' | 'techGeneration',
    opts: FacetOptionSchema[],
  ) => {
    if (!value) return;
    chips.push({
      key: `${field}:${value}`,
      label: nameOf(opts, value),
      remove: () => (filters[field] = null),
    });
  };

  single(filters.location, 'location', options.location);
  single(filters.person, 'person', options.person);
  single(filters.techGeneration, 'techGeneration', options.tech_gen);

  if (filters.yearMin != null || filters.yearMax != null) {
    const lo = filters.yearMin != null ? String(filters.yearMin) : '';
    const hi = filters.yearMax != null ? String(filters.yearMax) : '';
    chips.push({
      key: 'year',
      label: `Year: ${lo}–${hi}`,
      remove: () => {
        filters.yearMin = null;
        filters.yearMax = null;
      },
    });
  }

  return chips;
}
