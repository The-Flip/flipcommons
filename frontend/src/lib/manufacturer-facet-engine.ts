/**
 * Pure functions for client-side faceted filtering of manufacturers.
 * Mirrors facet-engine.ts but with manufacturer-specific dimensions.
 */

import type { FacetRef, FacetOption } from '$lib/facet-engine';
import { normalizeText } from '$lib/utils';

export type { FacetRef, FacetOption };

export interface MfrActiveFilterLabel {
  key: string;
  label: string;
  field: keyof MfrFilterState;
  value?: string;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FacetedManufacturer {
  name: string;
  slug: string;
  model_count: number;
  thumbnail_url?: string | null;
  search_text?: string | null;
  locations: FacetRef[];
  year_min?: number | null;
  year_max?: number | null;
  persons: FacetRef[];
  tech_generations: FacetRef[];
}

export interface MfrFilterState {
  query: string;
  location: string | null;
  yearMin: number | null;
  yearMax: number | null;
  person: string | null;
  techGeneration: string | null;
}

export interface MfrFacetCounts {
  location: Map<string, number>;
  person: Map<string, number>;
  techGeneration: Map<string, number>;
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

// ---------------------------------------------------------------------------
// URL <-> MfrFilterState serialization
// ---------------------------------------------------------------------------

const PARAM_MAP: {
  param: string;
  get: (f: MfrFilterState) => string | null;
  set: (f: MfrFilterState, v: string) => void;
}[] = [
  { param: 'q', get: (f) => f.query || null, set: (f, v) => (f.query = v) },
  { param: 'loc', get: (f) => f.location, set: (f, v) => (f.location = v) },
  {
    param: 'ymin',
    get: (f) => (f.yearMin != null ? String(f.yearMin) : null),
    set: (f, v) => (f.yearMin = Number(v)),
  },
  {
    param: 'ymax',
    get: (f) => (f.yearMax != null ? String(f.yearMax) : null),
    set: (f, v) => (f.yearMax = Number(v)),
  },
  { param: 'person', get: (f) => f.person, set: (f, v) => (f.person = v) },
  { param: 'gen', get: (f) => f.techGeneration, set: (f, v) => (f.techGeneration = v) },
];

export function mfrFiltersFromParams(sp: URLSearchParams): MfrFilterState {
  const f = emptyMfrFilterState();
  for (const { param, set } of PARAM_MAP) {
    const v = sp.get(param);
    if (v != null) set(f, v);
  }
  return f;
}

export function mfrFiltersToParams(f: MfrFilterState, sp: URLSearchParams): URLSearchParams {
  for (const { param } of PARAM_MAP) sp.delete(param);
  for (const { param, get } of PARAM_MAP) {
    const v = get(f);
    if (v != null) sp.set(param, v);
  }
  return sp;
}

// ---------------------------------------------------------------------------
// Individual filter predicates
// ---------------------------------------------------------------------------

type Predicate = (m: FacetedManufacturer) => boolean;

function matchesQuery(m: FacetedManufacturer, q: string): boolean {
  if (!q) return true;
  if (normalizeText(m.name).includes(q)) return true;
  if (m.search_text && normalizeText(m.search_text).includes(q)) return true;
  return false;
}

function matchesLocation(m: FacetedManufacturer, slug: string | null): boolean {
  if (!slug) return true;
  return m.locations.some((loc) => loc.public_id === slug);
}

function matchesYear(m: FacetedManufacturer, ymin: number | null, ymax: number | null): boolean {
  if (ymin == null && ymax == null) return true;
  if (m.year_min == null && m.year_max == null) return false;
  const mMin = m.year_min ?? m.year_max!;
  const mMax = m.year_max ?? m.year_min!;
  if (ymin != null && mMax < ymin) return false;
  if (ymax != null && mMin > ymax) return false;
  return true;
}

function matchesPerson(m: FacetedManufacturer, slug: string | null): boolean {
  if (!slug) return true;
  return m.persons.some((p) => p.public_id === slug);
}

function matchesTechGen(m: FacetedManufacturer, slug: string | null): boolean {
  if (!slug) return true;
  return m.tech_generations.some((tg) => tg.public_id === slug);
}

// ---------------------------------------------------------------------------
// Build per-dimension predicates
// ---------------------------------------------------------------------------

interface DimensionPredicates {
  query: Predicate;
  location: Predicate;
  year: Predicate;
  person: Predicate;
  techGeneration: Predicate;
}

function buildPredicates(state: MfrFilterState): DimensionPredicates {
  const q = normalizeText(state.query.trim());
  return {
    query: (m) => matchesQuery(m, q),
    location: (m) => matchesLocation(m, state.location),
    year: (m) => matchesYear(m, state.yearMin, state.yearMax),
    person: (m) => matchesPerson(m, state.person),
    techGeneration: (m) => matchesTechGen(m, state.techGeneration),
  };
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

export function filterManufacturers(
  manufacturers: FacetedManufacturer[],
  state: MfrFilterState,
): FacetedManufacturer[] {
  const preds = buildPredicates(state);
  const all = Object.values(preds);
  return manufacturers.filter((m) => all.every((p) => p(m)));
}

/**
 * Filter by the search query only, ignoring location / year / person / tech-gen
 * facets. Used by the "no results → create?" gate so that active facet filters
 * can't trick the UI into offering a duplicate-create affordance for a brand
 * the user just filtered out of view.
 */
export function filterManufacturersByQueryOnly(
  manufacturers: FacetedManufacturer[],
  query: string,
): FacetedManufacturer[] {
  const q = normalizeText(query.trim());
  if (!q) return manufacturers;
  return manufacturers.filter((m) => matchesQuery(m, q));
}

// ---------------------------------------------------------------------------
// Facet counts (N-1 approach)
// ---------------------------------------------------------------------------

export function computeMfrFacetCounts(
  manufacturers: FacetedManufacturer[],
  state: MfrFilterState,
): MfrFacetCounts {
  const preds = buildPredicates(state);
  const predKeys = Object.keys(preds) as (keyof DimensionPredicates)[];
  const predValues = Object.values(preds);

  // Compute a bitmask per manufacturer
  const masks = new Uint8Array(manufacturers.length);
  const allBits = (1 << predKeys.length) - 1;
  for (let i = 0; i < manufacturers.length; i++) {
    let mask = 0;
    for (let pi = 0; pi < predValues.length; pi++) {
      if (predValues[pi](manufacturers[i])) {
        mask |= 1 << pi;
      }
    }
    masks[i] = mask;
  }

  const dimIndex = (key: keyof DimensionPredicates) => predKeys.indexOf(key);

  function countFacetRefs(
    dimKey: keyof DimensionPredicates,
    extractor: (m: FacetedManufacturer) => FacetRef[],
  ): Map<string, number> {
    const excludeBit = 1 << dimIndex(dimKey);
    const requiredMask = allBits & ~excludeBit;
    const counts = new Map<string, number>();
    for (let i = 0; i < manufacturers.length; i++) {
      if ((masks[i] & requiredMask) === requiredMask) {
        for (const ref of extractor(manufacturers[i])) {
          counts.set(ref.public_id, (counts.get(ref.public_id) ?? 0) + 1);
        }
      }
    }
    return counts;
  }

  return {
    location: countFacetRefs('location', (m) => m.locations),
    person: countFacetRefs('person', (m) => m.persons),
    techGeneration: countFacetRefs('techGeneration', (m) => m.tech_generations),
  };
}

// ---------------------------------------------------------------------------
// Active filter label extraction
// ---------------------------------------------------------------------------

export function getMfrActiveFilterLabels(
  filters: MfrFilterState,
  allManufacturers: FacetedManufacturer[],
): MfrActiveFilterLabel[] {
  const labels: MfrActiveFilterLabel[] = [];

  // Build slug→name lookups
  const locationNames = new Map<string, string>();
  const personNames = new Map<string, string>();
  const techGenNames = new Map<string, string>();

  for (const m of allManufacturers) {
    for (const ref of m.locations) locationNames.set(ref.public_id, ref.name);
    for (const ref of m.persons) personNames.set(ref.public_id, ref.name);
    for (const ref of m.tech_generations) techGenNames.set(ref.public_id, ref.name);
  }

  if (filters.location) {
    labels.push({
      key: `location:${filters.location}`,
      label: locationNames.get(filters.location) ?? filters.location,
      field: 'location',
    });
  }
  if (filters.person) {
    labels.push({
      key: `person:${filters.person}`,
      label: personNames.get(filters.person) ?? filters.person,
      field: 'person',
    });
  }
  if (filters.techGeneration) {
    labels.push({
      key: `techGeneration:${filters.techGeneration}`,
      label: techGenNames.get(filters.techGeneration) ?? filters.techGeneration,
      field: 'techGeneration',
    });
  }
  if (filters.yearMin != null || filters.yearMax != null) {
    const parts: string[] = [];
    if (filters.yearMin != null) parts.push(String(filters.yearMin));
    parts.push('\u2013');
    if (filters.yearMax != null) parts.push(String(filters.yearMax));
    labels.push({
      key: 'year',
      label: `Year: ${parts.join('')}`,
      field: 'yearMin',
    });
  }

  return labels;
}
