/**
 * The /changesets filter query as a value: its state shape
 * (`ChangesFilterState`), the time-range vocabulary and the URL codec
 * (`changesFilterCodec`). Mirrors `$lib/filters/*` for a page whose filters
 * are UI concepts rather than backend fields: `range` is a named window that
 * `afterFor` resolves to the API's `after` timestamp at fetch time. No Svelte
 * imports — framework-agnostic and testable.
 */

import { CATALOG_ENTITY_KEYS, type CatalogEntityKey } from '$lib/entities/entity-meta';
import { serializeParams, type FilterCodec, type ParamKinds } from '$lib/filters/params';

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

/**
 * The selectable time windows, each a lookback from "now". The single
 * enumeration of the vocabulary: {@link ChangesTimeRange} derives from it and
 * the filter bar renders its options from it.
 */
export const CHANGES_TIME_RANGES = [
  { value: '24h', label: 'Last 24 hours', lookbackMs: 24 * HOUR_MS },
  { value: '7d', label: 'Last 7 days', lookbackMs: 7 * DAY_MS },
  { value: '30d', label: 'Last 30 days', lookbackMs: 30 * DAY_MS },
] as const;

/** A named lookback window, or `''` for all time. */
export type ChangesTimeRange = (typeof CHANGES_TIME_RANGES)[number]['value'] | '';

const TIME_RANGE_VALUES = CHANGES_TIME_RANGES.map((r) => r.value);

/** The /changesets filter state. `''` means "absent" for both dimensions. */
export type ChangesFilterState = {
  entity_type: CatalogEntityKey | '';
  range: ChangesTimeRange;
};

/** Narrowing membership test, so URL input can be validated without a cast at each call site. */
function isMember<T extends string>(value: string, allowed: readonly T[]): value is T {
  return (allowed as readonly string[]).includes(value);
}

/** Coerce raw input (a URL param, a `<select>` value) to a known entity type, or `''`. */
export function toEntityTypeFilter(raw: string | null): CatalogEntityKey | '' {
  const v = raw ?? '';
  return isMember(v, CATALOG_ENTITY_KEYS) ? v : '';
}

/** Coerce raw input (a URL param, a `<select>` value) to a known time range, or `''`. */
export function toTimeRangeFilter(raw: string | null): ChangesTimeRange {
  const v = raw ?? '';
  return isMember(v, TIME_RANGE_VALUES) ? v : '';
}

/**
 * The param declaration: both wire params are string scalars, keyed and
 * kind-checked against `ChangesFilterState`.
 */
const CHANGES_PARAMS: ParamKinds<ChangesFilterState> = {
  entity_type: 'string',
  range: 'string',
};

/**
 * The /changesets URL codec: filter state ⇄ the URL's search params. `parse`
 * validates rather than trusts, so a stale or hand-edited param lands as "no
 * filter" instead of a value the `<select>` can't show and the API can't match.
 */
export const changesFilterCodec: FilterCodec<ChangesFilterState> = {
  parse: (sp) => ({
    entity_type: toEntityTypeFilter(sp.get('entity_type')),
    range: toTimeRangeFilter(sp.get('range')),
  }),
  serialize: (f) => serializeParams(f, CHANGES_PARAMS),
  canonical: (f) => serializeParams(f, CHANGES_PARAMS).toString(),
};

/**
 * Resolve a time range to the API's `after` bound — `undefined` for all time.
 * Called per fetch so the window tracks the clock rather than page load.
 */
export function afterFor(range: ChangesTimeRange, now: Date = new Date()): string | undefined {
  const lookback = CHANGES_TIME_RANGES.find((r) => r.value === range);
  return lookback ? new Date(now.getTime() - lookback.lookbackMs).toISOString() : undefined;
}
