/**
 * Title filter state and its URL serialization, plus `matchesQuery` — the one pure
 * helper still shared after /titles moved filtering server-side (the kiosk title
 * typeahead). No Svelte imports — framework-agnostic and testable.
 */

import { normalizeText } from '$lib/utils';

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
  displayType: string | null;
  playerCount: number | null;
  system: string | null;
  franchise: string | null;
  series: string | null;
  ratingMin: number | null;
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
    displayType: null,
    playerCount: null,
    system: null,
    franchise: null,
    series: null,
    ratingMin: null,
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
    f.displayType != null ||
    f.playerCount != null ||
    f.system != null ||
    f.franchise != null ||
    f.series != null ||
    f.ratingMin != null
  );
}

// ---------------------------------------------------------------------------
// URL <-> FilterState serialization
// ---------------------------------------------------------------------------

/**
 * URL ⇄ FilterState mapping. Param names are the **real backend field names**
 * (one vocabulary end to end — URL params == `TitleFilterQuery` fields), so
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
  { param: 'tech_gen', get: (f) => f.techGeneration, set: (f, v) => (f.techGeneration = v) },
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
    param: 'feature',
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
  { param: 'display_type', get: (f) => f.displayType, set: (f, v) => (f.displayType = v) },
  {
    param: 'player_count',
    get: (f) => (f.playerCount != null ? String(f.playerCount) : null),
    set: (f, v) => (f.playerCount = toNum(v)),
  },
  { param: 'system', get: (f) => f.system, set: (f, v) => (f.system = v) },
  { param: 'franchise', get: (f) => f.franchise, set: (f, v) => (f.franchise = v) },
  { param: 'series', get: (f) => f.series, set: (f, v) => (f.series = v) },
  {
    param: 'rating_min',
    get: (f) => (f.ratingMin != null ? String(f.ratingMin) : null),
    set: (f, v) => (f.ratingMin = toNum(v)),
  },
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

// ---------------------------------------------------------------------------
// Query matching
// ---------------------------------------------------------------------------

/**
 * Match a record against a normalized query string. Checks name, abbreviations,
 * and manufacturer name. The parameter type is intentionally structural so
 * callers can pass any schema with these fields (e.g. TitleListItemSchema).
 * Used by /kiosk/edit's title typeahead.
 */
export function matchesQuery(
  t: {
    name: string;
    abbreviations: string[];
    manufacturer?: { name: string } | null;
  },
  q: string,
): boolean {
  if (!q) return true;
  return (
    normalizeText(t.name).includes(q) ||
    t.abbreviations.some((a) => normalizeText(a).includes(q)) ||
    (t.manufacturer?.name != null && normalizeText(t.manufacturer.name).includes(q))
  );
}
