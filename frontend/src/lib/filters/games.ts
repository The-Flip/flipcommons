/**
 * The /games filter query as a value: its state shape (`FilterState`), the
 * URL codec (`gameFilterCodec`) and the SSR API-query projection
 * (`apiQueryFromUrl`) — one vocabulary end to end (URL params ==
 * `GameFilterQuerySchema` fields). No Svelte imports — framework-agnostic and
 * testable.
 */

import type { GameFilterQuerySchema } from '$lib/api/schema';
import {
  parseParams,
  serializeParams,
  toNum,
  type Complete,
  type FilterCodec,
  type ParamSpec,
} from './params';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FilterState {
  query: string;
  techGeneration: string | null;
  yearMin: number | null;
  yearMax: number | null;
  manufacturer: string | null;
  person: string | null;
  themes: string[];
  features: string[];
  rewardTypes: string[];
  /** Relationship-filter wire values (`copy`, `copy:in`, `bootleg`…). */
  edges: string[];
  /**
   * The sparse dimensions hold raw wire values — vocabulary slugs plus the
   * reserved `unclassified` — because one UI selection can be two values
   * (`presetValues`); the shown selection derives via `sparseSelection`.
   */
  gameFormats: string[];
  productionStatuses: string[];
  cabinets: string[];
  displayType: string | null;
  playerCount: number | null;
  system: string | null;
  franchise: string | null;
  series: string | null;
}

/**
 * The reserved sparse-dimension wire value: "the field is unset". Never a
 * facet-payload option; labeled by the literal below.
 */
export const UNCLASSIFIED = 'unclassified';

/** Reader-facing label for the reserved `unclassified` value. */
export const UNCLASSIFIED_LABEL = 'Unclassified';

/**
 * What a null sparse field is read as at query time — not a pre-selected
 * filter. Twin of the backend `default_slug` declarations; a rename must
 * update both.
 */
export const SPARSE_DEFAULTS = {
  gameFormats: 'pinball',
  productionStatuses: 'produced',
  cabinets: 'floor',
} as const;

/** The sparse dimensions' `FilterState` field names. */
export type SparseField = keyof typeof SPARSE_DEFAULTS;

/**
 * The wire values a UI selection writes: the designated default widens to
 * `[slug, UNCLASSIFIED]`, any other value stays exact. Mirror of the backend
 * `preset_values`.
 */
export function presetValues(field: SparseField, slug: string): string[] {
  return slug === SPARSE_DEFAULTS[field] ? [slug, UNCLASSIFIED] : [slug];
}

/**
 * The dropdown selection a sparse dimension's raw values display as: the
 * preset pair reads as the default, a lone value as itself, any other union
 * as no selection (it degrades to per-value chips).
 */
export function sparseSelection(field: SparseField, values: string[]): string | null {
  if (values.length === 1) return values[0];
  const def = SPARSE_DEFAULTS[field];
  if (values.length === 2 && values.includes(def) && values.includes(UNCLASSIFIED)) {
    return def;
  }
  return null;
}

export function emptyFilterState(): FilterState {
  return {
    query: '',
    techGeneration: null,
    yearMin: null,
    yearMax: null,
    manufacturer: null,
    person: null,
    themes: [],
    features: [],
    rewardTypes: [],
    edges: [],
    gameFormats: [],
    productionStatuses: [],
    cabinets: [],
    displayType: null,
    playerCount: null,
    system: null,
    franchise: null,
    series: null,
  };
}

/**
 * Whether any structured filter is active — every dimension **except** the
 * free-text `query`. Drives the sidebar's "Clear all" affordance and the
 * create-prompt suppression (a zero result under an active facet doesn't mean
 * "this name doesn't exist"). `query` is excluded deliberately: the search box
 * has its own clear control and its own zero-result handling.
 */
export function hasActiveFilters(f: FilterState): boolean {
  return (
    f.techGeneration != null ||
    f.yearMin != null ||
    f.yearMax != null ||
    f.manufacturer != null ||
    f.person != null ||
    f.themes.length > 0 ||
    f.features.length > 0 ||
    f.rewardTypes.length > 0 ||
    f.edges.length > 0 ||
    f.gameFormats.length > 0 ||
    f.productionStatuses.length > 0 ||
    f.cabinets.length > 0 ||
    f.displayType != null ||
    f.playerCount != null ||
    f.system != null ||
    f.franchise != null ||
    f.series != null
  );
}

// ---------------------------------------------------------------------------
// URL <-> FilterState codec
// ---------------------------------------------------------------------------

/**
 * The dimensions filterable by URL but without a sidebar control —
 * `/games?tag=x` must filter the results, so `apiQueryFromUrl` reads them. The
 * codec neither parses nor serializes them: the first sidebar interaction
 * rebuilds the URL without them, so URL and results agree at every moment and
 * no filter persists without a visible, removable control.
 */
type HiddenGameParam = 'display_subtype' | 'tag' | 'technology_subgeneration' | 'corporate_entity';

/** The surfaced param vocabulary: every wire field the sidebar can drive. */
type SurfacedGameParam = Exclude<keyof GameFilterQuerySchema, HiddenGameParam>;

/**
 * URL ⇄ FilterState mapping, keyed by wire param name (one vocabulary end to
 * end — URL params == `GameFilterQuerySchema` fields) and typed against the
 * generated schema, so a dimension added to the backend is a compile error
 * here (after `make codegen`) until it gets a spec. Multi-value dimensions are
 * **repeated** params (`theme=a&theme=b`), read natively by the backend's
 * `list[str]` — not comma-joined.
 */
const GAME_PARAMS: Record<SurfacedGameParam, ParamSpec<FilterState>> = {
  q: { get: (f) => f.query || null, set: (f, v) => (f.query = v) },
  technology_generation: {
    get: (f) => f.techGeneration,
    set: (f, v) => (f.techGeneration = v),
  },
  year_min: {
    get: (f) => (f.yearMin != null ? String(f.yearMin) : null),
    set: (f, v) => (f.yearMin = toNum(v)),
  },
  year_max: {
    get: (f) => (f.yearMax != null ? String(f.yearMax) : null),
    set: (f, v) => (f.yearMax = toNum(v)),
  },
  manufacturer: { get: (f) => f.manufacturer, set: (f, v) => (f.manufacturer = v) },
  person: { get: (f) => f.person, set: (f, v) => (f.person = v) },
  theme: { multi: true, get: (f) => f.themes, set: (f, v) => (f.themes = v) },
  gameplay_feature: { multi: true, get: (f) => f.features, set: (f, v) => (f.features = v) },
  reward_type: { multi: true, get: (f) => f.rewardTypes, set: (f, v) => (f.rewardTypes = v) },
  edge: { multi: true, get: (f) => f.edges, set: (f, v) => (f.edges = v) },
  game_format: { multi: true, get: (f) => f.gameFormats, set: (f, v) => (f.gameFormats = v) },
  production_status: {
    multi: true,
    get: (f) => f.productionStatuses,
    set: (f, v) => (f.productionStatuses = v),
  },
  cabinet: { multi: true, get: (f) => f.cabinets, set: (f, v) => (f.cabinets = v) },
  display_type: { get: (f) => f.displayType, set: (f, v) => (f.displayType = v) },
  player_count: {
    get: (f) => (f.playerCount != null ? String(f.playerCount) : null),
    set: (f, v) => (f.playerCount = toNum(v)),
  },
  system: { get: (f) => f.system, set: (f, v) => (f.system = v) },
  franchise: { get: (f) => f.franchise, set: (f, v) => (f.franchise = v) },
  series: { get: (f) => f.series, set: (f, v) => (f.series = v) },
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
 * Read the full API query from a request URL: the codec's surfaced vocabulary
 * plus the hidden dimensions. Numeric coercion shares the codec's `toNum`; the
 * correspondence test pins the rest of the reading to what the codec writes.
 */
export function apiQueryFromUrl(url: URL): GamesApiQuery {
  const sp = url.searchParams;
  const str = (p: string): string | undefined => sp.get(p) || undefined;
  const num = (p: string): number | undefined => {
    const v = sp.get(p);
    return v == null ? undefined : (toNum(v) ?? undefined);
  };
  const multi = (p: string): string[] | undefined => {
    const vs = sp.getAll(p).filter(Boolean);
    return vs.length > 0 ? vs : undefined;
  };

  return {
    q: str('q'),
    manufacturer: str('manufacturer'),
    person: str('person'),
    technology_generation: str('technology_generation'),
    display_type: str('display_type'),
    system: str('system'),
    franchise: str('franchise'),
    series: str('series'),
    player_count: num('player_count'),
    year_min: num('year_min'),
    year_max: num('year_max'),
    theme: multi('theme'),
    gameplay_feature: multi('gameplay_feature'),
    reward_type: multi('reward_type'),
    edge: multi('edge'),
    game_format: multi('game_format'),
    production_status: multi('production_status'),
    cabinet: multi('cabinet'),
    display_subtype: str('display_subtype'),
    tag: str('tag'),
    technology_subgeneration: str('technology_subgeneration'),
    corporate_entity: str('corporate_entity'),
  };
}
