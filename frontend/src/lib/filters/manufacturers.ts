/**
 * The /manufacturers filter query as a value: its state shape
 * (`MfrFilterState`), the URL codec (`mfrFilterCodec`) and the SSR API-query
 * projection (`apiQueryFromUrl`) — one vocabulary end to end (state fields ==
 * URL params == `ManufacturerFilterQuerySchema` fields). Mirrors `games.ts`
 * for the smaller manufacturer vocabulary: all facets are single-value, and
 * there are no hidden or sparse dimensions. No Svelte imports —
 * framework-agnostic and testable.
 */

import type { ManufacturerFilterQuerySchema } from '$lib/api/schema';
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
 * The /manufacturers filter state: field names and types straight from the
 * generated schema. `null` and the empty string mean "absent".
 */
export type MfrFilterState = Required<ManufacturerFilterQuerySchema>;

export function emptyMfrFilterState(): MfrFilterState {
  return {
    q: '',
    location: null,
    year_min: null,
    year_max: null,
    person: null,
    technology_generation: null,
  };
}

/**
 * Whether any structured filter is active — every dimension **except** the
 * free-text `q` (the search box has its own clear control). Drives the
 * sidebar's "Clear all" affordance.
 */
export function hasActiveMfrFilters(f: MfrFilterState): boolean {
  return hasActiveParams(f);
}

// ---------------------------------------------------------------------------
// URL <-> MfrFilterState codec
// ---------------------------------------------------------------------------

/**
 * The param declaration: every wire param's kind, keyed and kind-checked
 * against `MfrFilterState` (itself the generated schema's field set), so a
 * dimension added to the backend is a compile error here (after
 * `make codegen`) until it is declared.
 */
const MFR_PARAMS: ParamKinds<MfrFilterState> = {
  q: 'string',
  location: 'string',
  year_min: 'number',
  year_max: 'number',
  person: 'string',
  technology_generation: 'string',
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

/** Read the full API query from a request URL: the codec's parse, empties stripped. */
export function apiQueryFromUrl(url: URL): MfrApiQuery {
  return stripEmpties(mfrFilterCodec.parse(url.searchParams));
}
