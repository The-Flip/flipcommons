/**
 * Title filter state and its URL serialization. No Svelte imports —
 * framework-agnostic and testable.
 */

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
// URL <-> FilterState serialization
// ---------------------------------------------------------------------------

/**
 * URL ⇄ FilterState mapping. Param names are the **real backend field names**
 * (one vocabulary end to end — URL params == `GameFilterQuerySchema` fields), so
 * `queryFromUrl` in the /titles route is a near-passthrough. Multi-value
 * dimensions are **repeated** params (`theme=a&theme=b`), read natively by the
 * backend's `list[str]` — not comma-joined.
 */
type SingleParam = {
  param: string;
  multi?: false;
  get: (f: FilterState) => string | null;
  set: (f: FilterState, v: string) => void;
};
type MultiParam = {
  param: string;
  multi: true;
  get: (f: FilterState) => string[];
  set: (f: FilterState, v: string[]) => void;
};
/** Parse a numeric URL param, falling back to null on non-finite input (e.g. a
 * hand-edited `?year_min=abc`) — mirrors `queryFromUrl`'s server-side guard so
 * the two URL parsers can't diverge into seeding `NaN`. */
function toNum(v: string): number | null {
  if (v.trim() === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

const PARAM_MAP: (SingleParam | MultiParam)[] = [
  { param: 'q', get: (f) => f.query || null, set: (f, v) => (f.query = v) },
  {
    param: 'technology_generation',
    get: (f) => f.techGeneration,
    set: (f, v) => (f.techGeneration = v),
  },
  {
    param: 'year_min',
    get: (f) => (f.yearMin != null ? String(f.yearMin) : null),
    set: (f, v) => (f.yearMin = toNum(v)),
  },
  {
    param: 'year_max',
    get: (f) => (f.yearMax != null ? String(f.yearMax) : null),
    set: (f, v) => (f.yearMax = toNum(v)),
  },
  { param: 'manufacturer', get: (f) => f.manufacturer, set: (f, v) => (f.manufacturer = v) },
  { param: 'person', get: (f) => f.person, set: (f, v) => (f.person = v) },
  {
    param: 'theme',
    multi: true,
    get: (f) => f.themes,
    set: (f, v) => (f.themes = v),
  },
  {
    param: 'gameplay_feature',
    multi: true,
    get: (f) => f.features,
    set: (f, v) => (f.features = v),
  },
  {
    param: 'reward_type',
    multi: true,
    get: (f) => f.rewardTypes,
    set: (f, v) => (f.rewardTypes = v),
  },
  {
    param: 'edge',
    multi: true,
    get: (f) => f.edges,
    set: (f, v) => (f.edges = v),
  },
  {
    param: 'game_format',
    multi: true,
    get: (f) => f.gameFormats,
    set: (f, v) => (f.gameFormats = v),
  },
  {
    param: 'production_status',
    multi: true,
    get: (f) => f.productionStatuses,
    set: (f, v) => (f.productionStatuses = v),
  },
  {
    param: 'cabinet',
    multi: true,
    get: (f) => f.cabinets,
    set: (f, v) => (f.cabinets = v),
  },
  { param: 'display_type', get: (f) => f.displayType, set: (f, v) => (f.displayType = v) },
  {
    param: 'player_count',
    get: (f) => (f.playerCount != null ? String(f.playerCount) : null),
    set: (f, v) => (f.playerCount = toNum(v)),
  },
  { param: 'system', get: (f) => f.system, set: (f, v) => (f.system = v) },
  { param: 'franchise', get: (f) => f.franchise, set: (f, v) => (f.franchise = v) },
  { param: 'series', get: (f) => f.series, set: (f, v) => (f.series = v) },
];

/** Read filter state from URL search params. */
export function filtersFromParams(sp: URLSearchParams): FilterState {
  const f = emptyFilterState();
  for (const spec of PARAM_MAP) {
    if (spec.multi) {
      const vs = sp.getAll(spec.param).filter(Boolean);
      if (vs.length > 0) spec.set(f, vs);
    } else {
      const v = sp.get(spec.param);
      if (v != null) spec.set(f, v);
    }
  }
  return f;
}

/** Write filter state to a URLSearchParams (mutates and returns it). */
export function filtersToParams(f: FilterState, sp: URLSearchParams): URLSearchParams {
  for (const { param } of PARAM_MAP) sp.delete(param);
  for (const spec of PARAM_MAP) {
    if (spec.multi) {
      for (const v of spec.get(f)) sp.append(spec.param, v);
    } else {
      const v = spec.get(f);
      if (v != null) sp.set(spec.param, v);
    }
  }
  return sp;
}
