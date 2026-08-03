import {
  UNCLASSIFIED,
  UNCLASSIFIED_LABEL,
  sparseSelection,
  type ChipOnlyGameParam,
  type FilterState,
  type SparseField,
} from '$lib/filters/games';
import { fieldPatch } from '$lib/filters/params';
import type { FacetOptionSchema, GameFilterOptionsSchema } from '$lib/api/schema';
import type { FilterChipSpec } from '$lib/components/collections/filters/ActiveFilterChips.svelte';
import { edgeFilterLabel } from '$lib/entities/relationship-phrase';

/**
 * Build the active-filter chips for /games from the current filter state.
 *
 * `options` are the streamed facet lists, used only to resolve slug → display
 * name — `undefined` while the stream is pending or failed, when labels
 * degrade to raw slugs (the chip row must render regardless: it is the only
 * removal affordance for the chip-only dimensions). The chips' `remove`
 * closures request the change through `apply`, one patch per chip — clicking
 * a chip clears exactly that filter.
 *
 * Pure and component-free so the chip set — labels, ordering, and what each
 * `remove` patches — can be unit-tested directly. Four shapes: single-select
 * fields (one chip, cleared to null), multi-select fields (one chip per value),
 * the bespoke scalar filters (player count, year range), and the chip-only
 * dimensions (no sidebar control; dimension-prefixed raw-slug labels).
 */
export function gameFilterChips(
  filters: FilterState,
  options: GameFilterOptionsSchema | undefined,
  apply: (patch: Partial<FilterState>) => void,
): FilterChipSpec[] {
  const chips: FilterChipSpec[] = [];
  const nameOf = (opts: FacetOptionSchema[] | undefined, slug: string): string =>
    opts?.find((o) => o.public_id === slug)?.name ?? slug;

  const single = (
    value: string | null,
    field:
      | 'technology_generation'
      | 'display_type'
      | 'manufacturer'
      | 'person'
      | 'system'
      | 'franchise'
      | 'series'
      | 'tag',
    opts: FacetOptionSchema[] | undefined,
  ) => {
    if (!value) return;
    chips.push({
      key: `${field}:${value}`,
      label: nameOf(opts, value),
      remove: () => apply(fieldPatch(field, null)),
    });
  };

  const multi = (
    values: string[],
    field: 'theme' | 'gameplay_feature' | 'reward_type',
    opts: FacetOptionSchema[] | undefined,
  ) => {
    for (const slug of values) {
      chips.push({
        key: `${field}:${slug}`,
        label: nameOf(opts, slug),
        remove: () =>
          apply(
            fieldPatch(
              field,
              filters[field].filter((s) => s !== slug),
            ),
          ),
      });
    }
  };

  /**
   * Canonical sparse states (preset pair, lone value) get one chip that
   * clears the whole dimension; an arbitrary URL-only union degrades to one
   * removable chip per raw value — the chip row is the only surface that
   * state shows on.
   */
  const sparse = (field: SparseField) => {
    const values = filters[field];
    if (values.length === 0) return;
    const facet = options?.[field];
    const labelOf = (v: string): string =>
      v === UNCLASSIFIED ? UNCLASSIFIED_LABEL : nameOf(facet?.options, v);
    const selection = sparseSelection(facet?.default_slug, values);
    if (selection != null) {
      chips.push({
        key: `${field}:${selection}`,
        label: labelOf(selection),
        remove: () => apply(fieldPatch(field, [])),
      });
      return;
    }
    for (const v of values) {
      chips.push({
        key: `${field}:${v}`,
        label: labelOf(v),
        remove: () =>
          apply(
            fieldPatch(
              field,
              filters[field].filter((s) => s !== v),
            ),
          ),
      });
    }
  };

  /**
   * A chip-only dimension's single chip: no sidebar control and no facet
   * payload, so the label is the dimension name plus the raw slug.
   */
  const chipOnly = (field: ChipOnlyGameParam, dimensionLabel: string) => {
    const value = filters[field];
    if (!value) return;
    chips.push({
      key: `${field}:${value}`,
      label: `${dimensionLabel}: ${value}`,
      remove: () => apply(fieldPatch(field, null)),
    });
  };

  single(filters.technology_generation, 'technology_generation', options?.technology_generation);
  single(filters.display_type, 'display_type', options?.display_type);
  single(filters.manufacturer, 'manufacturer', options?.manufacturer);
  single(filters.person, 'person', options?.person);
  multi(filters.theme, 'theme', options?.theme);
  multi(filters.gameplay_feature, 'gameplay_feature', options?.gameplay_feature);
  multi(filters.reward_type, 'reward_type', options?.reward_type);
  sparse('game_format');
  sparse('production_status');
  sparse('cabinet');
  // Edge labels come from the relationship vocabulary, not the option names —
  // the payload's option names are the wire values.
  for (const value of filters.edge) {
    chips.push({
      key: `edge:${value}`,
      label: edgeFilterLabel(value),
      remove: () => apply({ edge: filters.edge.filter((s) => s !== value) }),
    });
  }
  single(filters.system, 'system', options?.system);
  single(filters.franchise, 'franchise', options?.franchise);
  single(filters.series, 'series', options?.series);

  if (filters.player_count != null) {
    chips.push({
      key: `player_count:${filters.player_count}`,
      label: `${filters.player_count >= 6 ? '6+' : filters.player_count} players`,
      remove: () => apply({ player_count: null }),
    });
  }
  if (filters.year_min != null || filters.year_max != null) {
    const lo = filters.year_min != null ? String(filters.year_min) : '';
    const hi = filters.year_max != null ? String(filters.year_max) : '';
    chips.push({
      key: 'year',
      label: `Year: ${lo}–${hi}`,
      remove: () => apply({ year_min: null, year_max: null }),
    });
  }
  single(filters.tag, 'tag', options?.tag);

  chipOnly('display_subtype', 'Display subtype');
  chipOnly('technology_subgeneration', 'Technology subgeneration');
  chipOnly('corporate_entity', 'Corporate entity');

  return chips;
}
