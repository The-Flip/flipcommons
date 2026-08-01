import {
  UNCLASSIFIED,
  UNCLASSIFIED_LABEL,
  sparseSelection,
  type FilterState,
  type SparseField,
} from '$lib/facet-engine';
import type { FacetOptionSchema, GameFilterOptionsSchema } from '$lib/api/schema';
import type { FilterChipSpec } from '$lib/components/collections/filters/ActiveFilterChips.svelte';
import { edgeFilterLabel } from '$lib/entities/relationship-phrase';

/**
 * Build the active-filter chips for /games from the current filter state.
 *
 * `options` are the streamed facet lists, used only to resolve slug → display
 * name; the chips' `remove` closures mutate the passed `filters` object (the
 * page's bindable `$state`), so clicking a chip clears that filter reactively.
 *
 * Pure and component-free so the chip set — labels, ordering, and what each
 * `remove` clears — can be unit-tested directly. Three shapes: single-select
 * fields (one chip, cleared to null), multi-select fields (one chip per value),
 * and the bespoke scalar filters (player count, year range).
 */
export function gameFilterChips(
  filters: FilterState,
  options: GameFilterOptionsSchema,
): FilterChipSpec[] {
  const chips: FilterChipSpec[] = [];
  const nameOf = (opts: FacetOptionSchema[], slug: string): string =>
    opts.find((o) => o.public_id === slug)?.name ?? slug;

  const single = (
    value: string | null,
    field:
      | 'techGeneration'
      | 'displayType'
      | 'manufacturer'
      | 'person'
      | 'system'
      | 'franchise'
      | 'series',
    opts: FacetOptionSchema[],
  ) => {
    if (!value) return;
    chips.push({
      key: `${field}:${value}`,
      label: nameOf(opts, value),
      remove: () => (filters[field] = null),
    });
  };

  const multi = (
    values: string[],
    field: 'themes' | 'features' | 'rewardTypes',
    opts: FacetOptionSchema[],
  ) => {
    for (const slug of values) {
      chips.push({
        key: `${field}:${slug}`,
        label: nameOf(opts, slug),
        remove: () => (filters[field] = filters[field].filter((s) => s !== slug)),
      });
    }
  };

  /**
   * Canonical sparse states (preset pair, lone value) get one chip that
   * clears the whole dimension; an arbitrary URL-only union degrades to one
   * removable chip per raw value — the chip row is the only surface that
   * state shows on.
   */
  const sparse = (field: SparseField, opts: FacetOptionSchema[]) => {
    const values = filters[field];
    if (values.length === 0) return;
    const labelOf = (v: string): string =>
      v === UNCLASSIFIED ? UNCLASSIFIED_LABEL : nameOf(opts, v);
    const selection = sparseSelection(field, values);
    if (selection != null) {
      chips.push({
        key: `${field}:${selection}`,
        label: labelOf(selection),
        remove: () => (filters[field] = []),
      });
      return;
    }
    for (const v of values) {
      chips.push({
        key: `${field}:${v}`,
        label: labelOf(v),
        remove: () => (filters[field] = filters[field].filter((s) => s !== v)),
      });
    }
  };

  single(filters.techGeneration, 'techGeneration', options.tech_gen);
  single(filters.displayType, 'displayType', options.display_type);
  single(filters.manufacturer, 'manufacturer', options.manufacturer);
  single(filters.person, 'person', options.person);
  multi(filters.themes, 'themes', options.theme);
  multi(filters.features, 'features', options.feature);
  multi(filters.rewardTypes, 'rewardTypes', options.reward_type);
  sparse('gameFormats', options.game_format);
  sparse('productionStatuses', options.production_status);
  sparse('cabinets', options.cabinet);
  // Edge labels come from the relationship vocabulary, not the option names —
  // the payload's option names are the wire values.
  for (const value of filters.edges) {
    chips.push({
      key: `edges:${value}`,
      label: edgeFilterLabel(value),
      remove: () => (filters.edges = filters.edges.filter((s) => s !== value)),
    });
  }
  single(filters.system, 'system', options.system);
  single(filters.franchise, 'franchise', options.franchise);
  single(filters.series, 'series', options.series);

  if (filters.playerCount != null) {
    chips.push({
      key: `playerCount:${filters.playerCount}`,
      label: `${filters.playerCount >= 6 ? '6+' : filters.playerCount} players`,
      remove: () => (filters.playerCount = null),
    });
  }
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
