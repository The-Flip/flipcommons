/**
 * Manufacturer filter state and its URL serialization — the small surface that
 * survived /manufacturers moving filtering server-side (mirrors `facet-engine.ts`
 * for titles). Filtering, counts and option lists are all computed on the server now;
 * this module only maps the URL ⇄ the sidebar's reactive filter state. No Svelte
 * imports — framework-agnostic and testable.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MfrFilterState {
  query: string;
  location: string | null;
  yearMin: number | null;
  yearMax: number | null;
  person: string | null;
  techGeneration: string | null;
}

export function emptyMfrFilterState(): MfrFilterState {
  return {
    query: '',
    location: null,
    yearMin: null,
    yearMax: null,
    person: null,
    techGeneration: null,
  };
}

/**
 * Whether any structured filter is active — every dimension **except** the
 * free-text `query` (the search box has its own clear control). Drives the
 * sidebar's "Clear all" affordance.
 */
export function hasActiveMfrFilters(f: MfrFilterState): boolean {
  return (
    f.location != null ||
    f.yearMin != null ||
    f.yearMax != null ||
    f.person != null ||
    f.techGeneration != null
  );
}

// ---------------------------------------------------------------------------
// URL <-> MfrFilterState serialization
// ---------------------------------------------------------------------------

/**
 * Parse a numeric URL param, falling back to null on non-finite input (e.g. a
 * hand-edited `?year_min=abc`) — shared with `manufacturers-query.ts`'s server-side
 * guard so the two URL parsers can't diverge into seeding `NaN`.
 */
export function toNum(v: string): number | null {
  if (v.trim() === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * URL ⇄ MfrFilterState mapping. Param names are the **real backend field names**
 * (one vocabulary end to end — URL params == `ManufacturerFilterQuery` fields), so
 * `queryFromUrl` in the /manufacturers route is a near-passthrough. All facets are
 * single-value — no titles-style repeated multi-value params.
 */
const PARAM_MAP: {
  param: string;
  get: (f: MfrFilterState) => string | null;
  set: (f: MfrFilterState, v: string) => void;
}[] = [
  { param: 'q', get: (f) => f.query || null, set: (f, v) => (f.query = v) },
  { param: 'location', get: (f) => f.location, set: (f, v) => (f.location = v) },
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
  { param: 'person', get: (f) => f.person, set: (f, v) => (f.person = v) },
  { param: 'tech_gen', get: (f) => f.techGeneration, set: (f, v) => (f.techGeneration = v) },
];

/** Read filter state from URL search params. */
export function mfrFiltersFromParams(sp: URLSearchParams): MfrFilterState {
  const f = emptyMfrFilterState();
  for (const { param, set } of PARAM_MAP) {
    const v = sp.get(param);
    if (v != null) set(f, v);
  }
  return f;
}

/** Write filter state to a URLSearchParams (mutates and returns it). */
export function mfrFiltersToParams(f: MfrFilterState, sp: URLSearchParams): URLSearchParams {
  for (const { param } of PARAM_MAP) sp.delete(param);
  for (const { param, get } of PARAM_MAP) {
    const v = get(f);
    if (v != null) sp.set(param, v);
  }
  return sp;
}
