/**
 * The /games filter query as a value: its state shape (`FilterState`), the
 * URL codec (`gameFilterCodec`) and the SSR API-query projection
 * (`apiQueryFromUrl`) — one vocabulary end to end (state fields == URL params
 * == `GameFilterQuerySchema` fields). No Svelte imports — framework-agnostic
 * and testable.
 */

import type {
  GameFilterOptionsSchema,
  GameFilterQuerySchema,
  SparseFacetSchema,
} from '$lib/api/schema';
import {
  hasActiveParams,
  parseParams,
  serializeParams,
  stripEmpties,
  type Complete,
  type FilterCodec,
  type ParamKinds,
} from './params';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * The dimensions filterable by URL but without a sidebar control
 * (`/games?corporate_entity=x` — hand-crafted or external URLs; no facet
 * payload, so no option list). They live in `FilterState` like every other
 * dimension and persist across interactions; their only UI is the chip row,
 * which labels them by raw slug.
 */
export type ChipOnlyGameParam = 'display_subtype' | 'technology_subgeneration' | 'corporate_entity';

/**
 * The /games filter state: the full wire vocabulary, field names and
 * types straight from the generated schema. `null`, the empty string and the
 * empty array all mean "absent". The sparse dimensions (`SparseField`) hold
 * raw wire values — vocabulary slugs plus the reserved `unclassified` —
 * because one UI selection can be two values (`presetValues`); the shown
 * selection derives via `sparseSelection`.
 */
export type FilterState = Required<GameFilterQuerySchema>;

/**
 * The reserved sparse-dimension wire value: "the field is unset". Never a
 * facet-payload option; labeled by the literal below.
 */
export const UNCLASSIFIED = 'unclassified';

/** Reader-facing label for the reserved `unclassified` value. */
export const UNCLASSIFIED_LABEL = 'Unclassified';

/**
 * The sparse dimensions, derived from the facet payload: exactly the
 * `GameFilterOptionsSchema` fields whose facet ships as a `SparseFacetSchema`
 * — an option list nested with the `default_slug` a null field reads as.
 */
export type SparseField = {
  [K in keyof GameFilterOptionsSchema]: GameFilterOptionsSchema[K] extends SparseFacetSchema
    ? K
    : never;
}[keyof GameFilterOptionsSchema];

/**
 * The wire values a UI selection writes: the facet's designated default
 * widens to `[slug, UNCLASSIFIED]`, any other value stays exact. Mirror of
 * the backend `preset_values`. `defaultSlug` comes from the facet payload's
 * `default_slug`; it is undefined only while the payload is still streaming,
 * when no control is interactive yet — the selection then stays exact.
 */
export function presetValues(defaultSlug: string | undefined, slug: string): string[] {
  return slug === defaultSlug ? [slug, UNCLASSIFIED] : [slug];
}

/**
 * The dropdown selection a sparse dimension's raw values display as: the
 * preset pair reads as the default, a lone value as itself, any other union
 * as no selection (it degrades to per-value chips).
 */
export function sparseSelection(defaultSlug: string | undefined, values: string[]): string | null {
  if (values.length === 1) return values[0];
  if (
    defaultSlug != null &&
    values.length === 2 &&
    values.includes(defaultSlug) &&
    values.includes(UNCLASSIFIED)
  ) {
    return defaultSlug;
  }
  return null;
}

export function emptyFilterState(): FilterState {
  return {
    q: '',
    technology_generation: null,
    year_min: null,
    year_max: null,
    manufacturer: null,
    person: null,
    theme: [],
    gameplay_feature: [],
    reward_type: [],
    edge: [],
    game_format: [],
    production_status: [],
    cabinet: [],
    display_type: null,
    player_count: null,
    system: null,
    franchise: null,
    series: null,
    display_subtype: null,
    tag: null,
    technology_subgeneration: null,
    corporate_entity: null,
  };
}

/**
 * Whether any structured filter is active — every dimension **except** the
 * free-text `q`. Drives the sidebar's "Clear all" affordance and the
 * create-prompt suppression (a zero result under an active facet doesn't mean
 * "this name doesn't exist"). `q` is excluded deliberately: the search box
 * has its own clear control and its own zero-result handling.
 */
export function hasActiveFilters(f: FilterState): boolean {
  return hasActiveParams(f);
}

// ---------------------------------------------------------------------------
// URL <-> FilterState codec
// ---------------------------------------------------------------------------

/**
 * The param declaration: every wire param's kind. Keyed and kind-checked
 * against `FilterState` (itself the generated schema's field set), so a
 * dimension added to the backend is a compile error here (after
 * `make codegen`) until it is declared. Multi-value dimensions are
 * **repeated** params (`theme=a&theme=b`), read natively by the backend's
 * `list[str]` — not comma-joined.
 */
const GAME_PARAMS: ParamKinds<FilterState> = {
  q: 'string',
  technology_generation: 'string',
  year_min: 'number',
  year_max: 'number',
  manufacturer: 'string',
  person: 'string',
  theme: 'multi',
  gameplay_feature: 'multi',
  reward_type: 'multi',
  edge: 'multi',
  game_format: 'multi',
  production_status: 'multi',
  cabinet: 'multi',
  display_type: 'string',
  player_count: 'number',
  system: 'string',
  franchise: 'string',
  series: 'string',
  display_subtype: 'string',
  tag: 'string',
  technology_subgeneration: 'string',
  corporate_entity: 'string',
};

/** The /games URL codec: committed filter state ⇄ the URL's search params. */
export const gameFilterCodec: FilterCodec<FilterState> = {
  parse: (sp) => parseParams(sp, emptyFilterState(), GAME_PARAMS),
  serialize: (f) => serializeParams(f, GAME_PARAMS),
  canonical: (f) => serializeParams(f, GAME_PARAMS).toString(),
};

// ---------------------------------------------------------------------------
// URL -> API query (SSR)
// ---------------------------------------------------------------------------

/**
 * The `/api/games/` filter query (`page` added by the caller). Every schema
 * key is required — `undefined` when absent — so a new backend dimension is a
 * compile error in `apiQueryFromUrl` until it is read.
 */
export type GamesApiQuery = Complete<GameFilterQuerySchema>;

/**
 * Read the full API query from a request URL: the codec's parse, empties
 * stripped.
 */
export function apiQueryFromUrl(url: URL): GamesApiQuery {
  return stripEmpties(gameFilterCodec.parse(url.searchParams));
}
