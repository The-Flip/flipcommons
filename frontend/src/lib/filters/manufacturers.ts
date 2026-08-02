/**
 * The /manufacturers filter query as a value: its state shape
 * (`MfrFilterState`), the URL codec (`mfrFilterCodec`) and the SSR API-query
 * projection (`apiQueryFromUrl`) — one vocabulary end to end (URL params ==
 * `ManufacturerFilterQuerySchema` fields). Mirrors `games.ts` for the smaller
 * manufacturer vocabulary: all facets are single-value, and there are no
 * hidden dimensions. No Svelte imports — framework-agnostic and testable.
 */

import type { ManufacturerFilterQuerySchema } from '$lib/api/schema';
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
// URL <-> MfrFilterState codec
// ---------------------------------------------------------------------------

/**
 * URL ⇄ MfrFilterState mapping, keyed by wire param name (one vocabulary end
 * to end — URL params == `ManufacturerFilterQuerySchema` fields) and typed
 * against the generated schema, so a dimension added to the backend is a
 * compile error here (after `make codegen`) until it gets a spec.
 */
const MFR_PARAMS: Record<keyof ManufacturerFilterQuerySchema, ParamSpec<MfrFilterState>> = {
  q: { get: (f) => f.query || null, set: (f, v) => (f.query = v) },
  location: { get: (f) => f.location, set: (f, v) => (f.location = v) },
  year_min: {
    get: (f) => (f.yearMin != null ? String(f.yearMin) : null),
    set: (f, v) => (f.yearMin = toNum(v)),
  },
  year_max: {
    get: (f) => (f.yearMax != null ? String(f.yearMax) : null),
    set: (f, v) => (f.yearMax = toNum(v)),
  },
  person: { get: (f) => f.person, set: (f, v) => (f.person = v) },
  technology_generation: {
    get: (f) => f.techGeneration,
    set: (f, v) => (f.techGeneration = v),
  },
};

/** The /manufacturers URL codec: committed filter state ⇄ the URL's search params. */
export const mfrFilterCodec: FilterCodec<MfrFilterState> = {
  parse: (sp) => parseParams(sp, emptyMfrFilterState(), MFR_PARAMS),
  serialize: (f) => serializeParams(f, MFR_PARAMS),
  canonical: (f) => serializeParams(f, MFR_PARAMS).toString(),
};

// ---------------------------------------------------------------------------
// URL -> API query (SSR)
// ---------------------------------------------------------------------------

/**
 * The `/api/manufacturers/` filter query (`page` added by the caller). Every
 * schema key is required — `undefined` when absent — so a new backend
 * dimension is a compile error in `apiQueryFromUrl` until it is read.
 */
export type MfrApiQuery = Complete<ManufacturerFilterQuerySchema>;

/**
 * Read the full API query from a request URL. Numeric coercion shares the
 * codec's `toNum`; the correspondence test pins the rest of the reading to
 * what the codec writes.
 */
export function apiQueryFromUrl(url: URL): MfrApiQuery {
  const sp = url.searchParams;
  const str = (p: string): string | undefined => sp.get(p) || undefined;
  const num = (p: string): number | undefined => {
    const v = sp.get(p);
    return v == null ? undefined : (toNum(v) ?? undefined);
  };

  return {
    q: str('q'),
    location: str('location'),
    person: str('person'),
    technology_generation: str('technology_generation'),
    year_min: num('year_min'),
    year_max: num('year_max'),
  };
}
