import type { MfrFilterState } from '$lib/filters/manufacturers';
import { fieldPatch } from '$lib/filters/params';
import type { FacetOptionSchema, ManufacturerFilterOptionsSchema } from '$lib/api/schema';
import type { FilterChipSpec } from '$lib/components/collections/filters/ActiveFilterChips.svelte';

/**
 * Build the active-filter chips for /manufacturers from the current filter state.
 *
 * `options` are the streamed facet lists, used only to resolve public_id → display
 * name — `undefined` while the stream is pending or failed, when labels degrade to
 * raw slugs. The chips' `remove` closures request the change through `apply`, one
 * patch per chip. Pure and component-free so the chip set can be unit-tested
 * directly. Mirrors `games-filter-chips`; all manufacturer facets are
 * single-select plus a year range.
 */
export function manufacturerFilterChips(
  filters: MfrFilterState,
  options: ManufacturerFilterOptionsSchema | undefined,
  apply: (patch: Partial<MfrFilterState>) => void,
): FilterChipSpec[] {
  const chips: FilterChipSpec[] = [];
  const nameOf = (opts: FacetOptionSchema[] | undefined, id: string): string =>
    opts?.find((o) => o.public_id === id)?.name ?? id;

  const single = (
    value: string | null,
    field: 'location' | 'person' | 'technology_generation',
    opts: FacetOptionSchema[] | undefined,
  ) => {
    if (!value) return;
    chips.push({
      key: `${field}:${value}`,
      label: nameOf(opts, value),
      remove: () => apply(fieldPatch(field, null)),
    });
  };

  single(filters.location, 'location', options?.location);
  single(filters.person, 'person', options?.person);
  single(filters.technology_generation, 'technology_generation', options?.technology_generation);

  if (filters.year_min != null || filters.year_max != null) {
    const lo = filters.year_min != null ? String(filters.year_min) : '';
    const hi = filters.year_max != null ? String(filters.year_max) : '';
    chips.push({
      key: 'year',
      label: `Year: ${lo}–${hi}`,
      remove: () => apply({ year_min: null, year_max: null }),
    });
  }

  return chips;
}
