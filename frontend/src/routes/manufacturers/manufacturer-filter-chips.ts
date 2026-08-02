import type { MfrFilterState } from '$lib/filters/manufacturers';
import type { FacetOptionSchema, ManufacturerFilterOptionsSchema } from '$lib/api/schema';
import type { FilterChipSpec } from '$lib/components/collections/filters/ActiveFilterChips.svelte';

/**
 * Build the active-filter chips for /manufacturers from the current filter state.
 *
 * `options` are the streamed facet lists, used only to resolve public_id → display
 * name; the chips' `remove` closures mutate the passed `filters` object (the page's
 * bindable `$state`), so clicking a chip clears that filter reactively. Pure and
 * component-free so the chip set can be unit-tested directly. Mirrors
 * `games-filter-chips`; all manufacturer facets are single-select plus a year range.
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
    field: 'location' | 'person' | 'technology_generation',
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
  single(filters.technology_generation, 'technology_generation', options.technology_generation);

  if (filters.year_min != null || filters.year_max != null) {
    const lo = filters.year_min != null ? String(filters.year_min) : '';
    const hi = filters.year_max != null ? String(filters.year_max) : '';
    chips.push({
      key: 'year',
      label: `Year: ${lo}–${hi}`,
      remove: () => {
        filters.year_min = null;
        filters.year_max = null;
      },
    });
  }

  return chips;
}
