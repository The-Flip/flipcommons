/**
 * Pure functions for client-side faceted filtering and count computation.
 * No Svelte imports — this module is framework-agnostic and testable.
 */

import { normalizeText } from '$lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FacetRef {
  public_id: string;
  name: string;
}

export interface FacetedTitle {
  name: string;
  slug: string;
  abbreviations: string[];
  model_count: number;
  manufacturer?: { public_id: string; name: string } | null;
  year?: number | null;
  thumbnail_url?: string | null;
  tech_generations: FacetRef[];
  display_types: FacetRef[];
  player_counts: number[];
  systems: FacetRef[];
  themes: FacetRef[];
  gameplay_features: FacetRef[];
  reward_types: FacetRef[];
  persons: FacetRef[];
  franchise?: FacetRef | null;
  series?: FacetRef | null;
  year_min?: number | null;
  year_max?: number | null;
  ipdb_rating_max?: number | null;
}

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

export interface FacetCounts {
  techGeneration: Map<string, number>;
  manufacturer: Map<string, number>;
  person: Map<string, number>;
  theme: Map<string, number>;
  feature: Map<string, number>;
  rewardType: Map<string, number>;
  displayType: Map<string, number>;
  playerCount: Map<number, number>;
  system: Map<string, number>;
  franchise: Map<string, number>;
  series: Map<string, number>;
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

// ---------------------------------------------------------------------------
// URL <-> FilterState serialization
// ---------------------------------------------------------------------------

/** Param name → how to read it from FilterState */
const PARAM_MAP: {
  param: string;
  get: (f: FilterState) => string | null;
  set: (f: FilterState, v: string) => void;
}[] = [
  { param: 'q', get: (f) => f.query || null, set: (f, v) => (f.query = v) },
  { param: 'gen', get: (f) => f.techGeneration, set: (f, v) => (f.techGeneration = v) },
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
  { param: 'mfr', get: (f) => f.manufacturer, set: (f, v) => (f.manufacturer = v) },
  { param: 'person', get: (f) => f.person, set: (f, v) => (f.person = v) },
  {
    param: 'theme',
    get: (f) => (f.themes.length > 0 ? f.themes.join(',') : null),
    set: (f, v) => (f.themes = v.split(',').filter(Boolean)),
  },
  {
    param: 'feat',
    get: (f) => (f.features.length > 0 ? f.features.join(',') : null),
    set: (f, v) => (f.features = v.split(',').filter(Boolean)),
  },
  {
    param: 'rtype',
    get: (f) => (f.rewardTypes.length > 0 ? f.rewardTypes.join(',') : null),
    set: (f, v) => (f.rewardTypes = v.split(',').filter(Boolean)),
  },
  { param: 'display', get: (f) => f.displayType, set: (f, v) => (f.displayType = v) },
  {
    param: 'players',
    get: (f) => (f.playerCount != null ? String(f.playerCount) : null),
    set: (f, v) => (f.playerCount = Number(v)),
  },
  { param: 'sys', get: (f) => f.system, set: (f, v) => (f.system = v) },
  { param: 'franchise', get: (f) => f.franchise, set: (f, v) => (f.franchise = v) },
  { param: 'series', get: (f) => f.series, set: (f, v) => (f.series = v) },
  {
    param: 'rating',
    get: (f) => (f.ratingMin != null ? String(f.ratingMin) : null),
    set: (f, v) => (f.ratingMin = Number(v)),
  },
];

/** Read filter state from URL search params. */
export function filtersFromParams(sp: URLSearchParams): FilterState {
  const f = emptyFilterState();
  for (const { param, set } of PARAM_MAP) {
    const v = sp.get(param);
    if (v != null) set(f, v);
  }
  return f;
}

/** Write filter state to a URLSearchParams (mutates and returns it). */
export function filtersToParams(f: FilterState, sp: URLSearchParams): URLSearchParams {
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

type Predicate = (t: FacetedTitle) => boolean;

/**
 * Match a title against a normalized query string. Checks name, abbreviations,
 * and manufacturer name. The parameter type is intentionally structural so
 * callers can pass any schema with these fields (e.g. TitleListItemSchema).
 * Reused by /titles/+page.svelte and /kiosk/configure.
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

function matchesTechGen(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.tech_generations.some((tg) => tg.public_id === slug);
}

function matchesYear(t: FacetedTitle, ymin: number | null, ymax: number | null): boolean {
  if (ymin == null && ymax == null) return true;
  const tmin = t.year_min ?? t.year;
  const tmax = t.year_max ?? t.year;
  if (tmin == null && tmax == null) return false;
  if (ymin != null && (tmax ?? tmin!) < ymin) return false;
  if (ymax != null && (tmin ?? tmax!) > ymax) return false;
  return true;
}

function matchesManufacturer(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.manufacturer?.public_id === slug;
}

function matchesPerson(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.persons.some((p) => p.public_id === slug);
}

function matchesThemes(t: FacetedTitle, slugs: string[]): boolean {
  if (slugs.length === 0) return true;
  const titleThemes = new Set(t.themes.map((th) => th.public_id));
  return slugs.every((s) => titleThemes.has(s));
}

function matchesFeatures(t: FacetedTitle, slugs: string[]): boolean {
  if (slugs.length === 0) return true;
  const titleFeatures = new Set(t.gameplay_features.map((f) => f.public_id));
  return slugs.every((s) => titleFeatures.has(s));
}

function matchesRewardTypes(t: FacetedTitle, slugs: string[]): boolean {
  if (slugs.length === 0) return true;
  const titleRewardTypes = new Set(t.reward_types.map((r) => r.public_id));
  return slugs.every((s) => titleRewardTypes.has(s));
}

function matchesDisplayType(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.display_types.some((d) => d.public_id === slug);
}

function matchesPlayerCount(t: FacetedTitle, count: number | null): boolean {
  if (count == null) return true;
  if (count >= 6) return t.player_counts.some((p) => p >= 6);
  return t.player_counts.includes(count);
}

function matchesSystem(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.systems.some((s) => s.public_id === slug);
}

function matchesFranchise(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.franchise?.public_id === slug;
}

function matchesSeries(t: FacetedTitle, slug: string | null): boolean {
  if (!slug) return true;
  return t.series?.public_id === slug;
}

function matchesRating(t: FacetedTitle, min: number | null): boolean {
  if (min == null) return true;
  return t.ipdb_rating_max != null && t.ipdb_rating_max >= min;
}

// ---------------------------------------------------------------------------
// Build per-dimension predicates
// ---------------------------------------------------------------------------

interface DimensionPredicates {
  query: Predicate;
  techGeneration: Predicate;
  year: Predicate;
  manufacturer: Predicate;
  person: Predicate;
  themes: Predicate;
  features: Predicate;
  rewardTypes: Predicate;
  displayType: Predicate;
  playerCount: Predicate;
  system: Predicate;
  franchise: Predicate;
  series: Predicate;
  rating: Predicate;
}

function buildPredicates(state: FilterState): DimensionPredicates {
  const q = normalizeText(state.query.trim());
  return {
    query: (t) => matchesQuery(t, q),
    techGeneration: (t) => matchesTechGen(t, state.techGeneration),
    year: (t) => matchesYear(t, state.yearMin, state.yearMax),
    manufacturer: (t) => matchesManufacturer(t, state.manufacturer),
    person: (t) => matchesPerson(t, state.person),
    themes: (t) => matchesThemes(t, state.themes),
    features: (t) => matchesFeatures(t, state.features),
    rewardTypes: (t) => matchesRewardTypes(t, state.rewardTypes),
    displayType: (t) => matchesDisplayType(t, state.displayType),
    playerCount: (t) => matchesPlayerCount(t, state.playerCount),
    system: (t) => matchesSystem(t, state.system),
    franchise: (t) => matchesFranchise(t, state.franchise),
    series: (t) => matchesSeries(t, state.series),
    rating: (t) => matchesRating(t, state.ratingMin),
  };
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

export function filterTitles(titles: FacetedTitle[], state: FilterState): FacetedTitle[] {
  const preds = buildPredicates(state);
  const all = Object.values(preds);
  return titles.filter((t) => all.every((p) => p(t)));
}

// ---------------------------------------------------------------------------
// Facet counts (N-1 approach)
// ---------------------------------------------------------------------------

/**
 * For each dimension D, compute the count of each value of D across titles
 * that pass ALL filters EXCEPT D. This gives the correct dynamic counts.
 */
export function computeFacetCounts(titles: FacetedTitle[], state: FilterState): FacetCounts {
  const preds = buildPredicates(state);
  const predKeys = Object.keys(preds) as (keyof DimensionPredicates)[];
  const predValues = Object.values(preds);

  // Compute a bitmask per title: bit i is set if title passes predicate i
  const masks = new Uint16Array(titles.length);
  const allBits = (1 << predKeys.length) - 1;
  for (let ti = 0; ti < titles.length; ti++) {
    let mask = 0;
    for (let pi = 0; pi < predValues.length; pi++) {
      if (predValues[pi](titles[ti])) {
        mask |= 1 << pi;
      }
    }
    masks[ti] = mask;
  }

  // Helper: get index of a dimension key
  const dimIndex = (key: keyof DimensionPredicates) => predKeys.indexOf(key);

  // Helper: count facet values for a dimension, excluding that dimension's filter
  function countFacetRefs(
    dimKey: keyof DimensionPredicates,
    extractor: (t: FacetedTitle) => FacetRef[],
  ): Map<string, number> {
    const excludeBit = 1 << dimIndex(dimKey);
    const requiredMask = allBits & ~excludeBit;
    const counts = new Map<string, number>();
    for (let ti = 0; ti < titles.length; ti++) {
      if ((masks[ti] & requiredMask) === requiredMask) {
        for (const ref of extractor(titles[ti])) {
          counts.set(ref.public_id, (counts.get(ref.public_id) ?? 0) + 1);
        }
      }
    }
    return counts;
  }

  function countSingleRef(
    dimKey: keyof DimensionPredicates,
    extractor: (t: FacetedTitle) => FacetRef | null | undefined,
  ): Map<string, number> {
    const excludeBit = 1 << dimIndex(dimKey);
    const requiredMask = allBits & ~excludeBit;
    const counts = new Map<string, number>();
    for (let ti = 0; ti < titles.length; ti++) {
      if ((masks[ti] & requiredMask) === requiredMask) {
        const ref = extractor(titles[ti]);
        if (ref) {
          counts.set(ref.public_id, (counts.get(ref.public_id) ?? 0) + 1);
        }
      }
    }
    return counts;
  }

  function countNumbers(
    dimKey: keyof DimensionPredicates,
    extractor: (t: FacetedTitle) => number[],
  ): Map<number, number> {
    const excludeBit = 1 << dimIndex(dimKey);
    const requiredMask = allBits & ~excludeBit;
    const counts = new Map<number, number>();
    for (let ti = 0; ti < titles.length; ti++) {
      if ((masks[ti] & requiredMask) === requiredMask) {
        for (const val of extractor(titles[ti])) {
          counts.set(val, (counts.get(val) ?? 0) + 1);
        }
      }
    }
    return counts;
  }

  return {
    techGeneration: countFacetRefs('techGeneration', (t) => t.tech_generations),
    manufacturer: countSingleRef('manufacturer', (t) => t.manufacturer ?? null),
    person: countFacetRefs('person', (t) => t.persons),
    theme: countFacetRefs('themes', (t) => t.themes),
    feature: countFacetRefs('features', (t) => t.gameplay_features),
    rewardType: countFacetRefs('rewardTypes', (t) => t.reward_types),
    displayType: countFacetRefs('displayType', (t) => t.display_types),
    playerCount: countNumbers('playerCount', (t) => t.player_counts),
    system: countFacetRefs('system', (t) => t.systems),
    franchise: countSingleRef('franchise', (t) => t.franchise),
    series: countSingleRef('series', (t) => t.series),
  };
}

// ---------------------------------------------------------------------------
// Option list builders (extract unique {slug, name} from all titles)
// ---------------------------------------------------------------------------

export interface FacetOption {
  slug: string;
  label: string;
  count: number;
}

export function buildFacetRefOptions<T>(
  items: T[],
  extractor: (t: T) => FacetRef[],
  counts: Map<string, number>,
): FacetOption[] {
  const seen = new Map<string, string>();
  for (const t of items) {
    for (const ref of extractor(t)) {
      if (!seen.has(ref.public_id)) seen.set(ref.public_id, ref.name);
    }
  }
  return Array.from(seen.entries()).map(([publicId, name]) => ({
    slug: publicId,
    label: name,
    count: counts.get(publicId) ?? 0,
  }));
}

export function buildSingleRefOptions<T>(
  items: T[],
  extractor: (t: T) => FacetRef | null | undefined,
  counts: Map<string, number>,
): FacetOption[] {
  const seen = new Map<string, string>();
  for (const t of items) {
    const ref = extractor(t);
    if (ref && !seen.has(ref.public_id)) seen.set(ref.public_id, ref.name);
  }
  return Array.from(seen.entries()).map(([publicId, name]) => ({
    slug: publicId,
    label: name,
    count: counts.get(publicId) ?? 0,
  }));
}

// ---------------------------------------------------------------------------
// Active filter label extraction (for removable chip display)
// ---------------------------------------------------------------------------

export interface ActiveFilterLabel {
  /** Unique key for keyed-each, e.g. "techGeneration:solid-state" */
  key: string;
  /** Human-readable label, e.g. "Solid State" */
  label: string;
  /** Which filter field this belongs to (for removal) */
  field: keyof FilterState;
  /** For themes (array field), which specific slug to remove */
  value?: string;
}

export function getActiveFilterLabels(
  filters: FilterState,
  allTitles: FacetedTitle[],
): ActiveFilterLabel[] {
  const labels: ActiveFilterLabel[] = [];

  // Build slug→name lookup maps by scanning allTitles once
  const techGenNames = new Map<string, string>();
  const displayTypeNames = new Map<string, string>();
  const manufacturerNames = new Map<string, string>();
  const personNames = new Map<string, string>();
  const themeNames = new Map<string, string>();
  const featureNames = new Map<string, string>();
  const rewardTypeNames = new Map<string, string>();
  const systemNames = new Map<string, string>();
  const franchiseNames = new Map<string, string>();
  const seriesNames = new Map<string, string>();

  for (const t of allTitles) {
    for (const ref of t.tech_generations) techGenNames.set(ref.public_id, ref.name);
    for (const ref of t.display_types) displayTypeNames.set(ref.public_id, ref.name);
    if (t.manufacturer) manufacturerNames.set(t.manufacturer.public_id, t.manufacturer.name);
    for (const ref of t.persons) personNames.set(ref.public_id, ref.name);
    for (const ref of t.themes) themeNames.set(ref.public_id, ref.name);
    for (const ref of t.gameplay_features) featureNames.set(ref.public_id, ref.name);
    for (const ref of t.reward_types) rewardTypeNames.set(ref.public_id, ref.name);
    for (const ref of t.systems) systemNames.set(ref.public_id, ref.name);
    if (t.franchise) franchiseNames.set(t.franchise.public_id, t.franchise.name);
    if (t.series) seriesNames.set(t.series.public_id, t.series.name);
  }

  if (filters.techGeneration) {
    labels.push({
      key: `techGeneration:${filters.techGeneration}`,
      label: techGenNames.get(filters.techGeneration) ?? filters.techGeneration,
      field: 'techGeneration',
    });
  }
  if (filters.displayType) {
    labels.push({
      key: `displayType:${filters.displayType}`,
      label: displayTypeNames.get(filters.displayType) ?? filters.displayType,
      field: 'displayType',
    });
  }
  if (filters.manufacturer) {
    labels.push({
      key: `manufacturer:${filters.manufacturer}`,
      label: manufacturerNames.get(filters.manufacturer) ?? filters.manufacturer,
      field: 'manufacturer',
    });
  }
  if (filters.person) {
    labels.push({
      key: `person:${filters.person}`,
      label: personNames.get(filters.person) ?? filters.person,
      field: 'person',
    });
  }
  for (const slug of filters.themes) {
    labels.push({
      key: `themes:${slug}`,
      label: themeNames.get(slug) ?? slug,
      field: 'themes',
      value: slug,
    });
  }
  for (const slug of filters.features) {
    labels.push({
      key: `features:${slug}`,
      label: featureNames.get(slug) ?? slug,
      field: 'features',
      value: slug,
    });
  }
  for (const slug of filters.rewardTypes) {
    labels.push({
      key: `rewardTypes:${slug}`,
      label: rewardTypeNames.get(slug) ?? slug,
      field: 'rewardTypes',
      value: slug,
    });
  }
  if (filters.playerCount != null) {
    labels.push({
      key: `playerCount:${filters.playerCount}`,
      label: `${filters.playerCount >= 6 ? '6+' : filters.playerCount} players`,
      field: 'playerCount',
    });
  }
  if (filters.system) {
    labels.push({
      key: `system:${filters.system}`,
      label: systemNames.get(filters.system) ?? filters.system,
      field: 'system',
    });
  }
  if (filters.franchise) {
    labels.push({
      key: `franchise:${filters.franchise}`,
      label: franchiseNames.get(filters.franchise) ?? filters.franchise,
      field: 'franchise',
    });
  }
  if (filters.series) {
    labels.push({
      key: `series:${filters.series}`,
      label: seriesNames.get(filters.series) ?? filters.series,
      field: 'series',
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
  if (filters.ratingMin != null) {
    labels.push({
      key: 'ratingMin',
      label: `Rating \u2265 ${filters.ratingMin}`,
      field: 'ratingMin',
    });
  }

  return labels;
}

// ---------------------------------------------------------------------------
// Theme hierarchy expansion — adds ancestor themes to each title so that
// filtering by a parent theme (e.g. "Sports") also matches titles whose
// models only have a child theme (e.g. "Air Racing").
// ---------------------------------------------------------------------------

interface ThemeHierarchyEntry {
  slug: string;
  name: string;
  parent_slugs: string[];
}

/**
 * Build a map from each theme slug to the set of all ancestor slugs
 * (transitive closure, including itself).
 */
function buildAncestorMap(themes: ThemeHierarchyEntry[]): Map<string, Set<string>> {
  const parentMap = new Map<string, string[]>();
  for (const t of themes) {
    parentMap.set(t.slug, t.parent_slugs);
  }

  const cache = new Map<string, Set<string>>();

  function ancestors(slug: string, visited: Set<string>): Set<string> {
    if (cache.has(slug)) return cache.get(slug)!;
    const result = new Set<string>([slug]);
    if (visited.has(slug)) return result; // cycle guard
    visited.add(slug);
    for (const p of parentMap.get(slug) ?? []) {
      for (const a of ancestors(p, visited)) {
        result.add(a);
      }
    }
    cache.set(slug, result);
    return result;
  }

  for (const t of themes) {
    ancestors(t.slug, new Set());
  }
  return cache;
}

/**
 * Expand each title's `.themes` to include all ancestor themes.
 * Returns new title objects (does not mutate the originals).
 */
export function expandTitlesWithAncestorThemes(
  titles: FacetedTitle[],
  themeHierarchy: ThemeHierarchyEntry[],
): FacetedTitle[] {
  if (themeHierarchy.length === 0) return titles;

  const ancestorMap = buildAncestorMap(themeHierarchy);
  const nameMap = new Map<string, string>();
  for (const t of themeHierarchy) {
    nameMap.set(t.slug, t.name);
  }

  return titles.map((title) => {
    if (title.themes.length === 0) return title;

    const expanded = new Map<string, string>();
    for (const theme of title.themes) {
      const allAncestors = ancestorMap.get(theme.public_id);
      if (allAncestors) {
        for (const slug of allAncestors) {
          if (!expanded.has(slug)) {
            expanded.set(slug, nameMap.get(slug) ?? slug);
          }
        }
      } else {
        expanded.set(theme.public_id, theme.name);
      }
    }

    return {
      ...title,
      themes: Array.from(expanded.entries()).map(([public_id, name]) => ({
        public_id,
        name,
      })),
    };
  });
}

export interface GameplayFeatureHierarchyEntry {
  slug: string;
  name: string;
  parent_slugs: string[];
}

/**
 * Expand each title's `.gameplay_features` to include all ancestor features.
 * Returns new title objects (does not mutate the originals).
 */
export function expandTitlesWithAncestorFeatures(
  titles: FacetedTitle[],
  featureHierarchy: GameplayFeatureHierarchyEntry[],
): FacetedTitle[] {
  if (featureHierarchy.length === 0) return titles;

  const ancestorMap = buildAncestorMap(featureHierarchy);
  const nameMap = new Map<string, string>();
  for (const f of featureHierarchy) {
    nameMap.set(f.slug, f.name);
  }

  return titles.map((title) => {
    if (title.gameplay_features.length === 0) return title;

    const expanded = new Map<string, string>();
    for (const feature of title.gameplay_features) {
      const allAncestors = ancestorMap.get(feature.public_id);
      if (allAncestors) {
        for (const slug of allAncestors) {
          if (!expanded.has(slug)) {
            expanded.set(slug, nameMap.get(slug) ?? slug);
          }
        }
      } else {
        expanded.set(feature.public_id, feature.name);
      }
    }

    return {
      ...title,
      gameplay_features: Array.from(expanded.entries()).map(([public_id, name]) => ({
        public_id,
        name,
      })),
    };
  });
}

export function buildPlayerCountOptions(
  counts: Map<number, number>,
): { value: number; label: string; count: number }[] {
  // Group 6+ together
  const grouped = new Map<number, number>();
  for (const [pc, ct] of counts) {
    if (pc >= 6) {
      grouped.set(6, (grouped.get(6) ?? 0) + ct);
    } else {
      grouped.set(pc, (grouped.get(pc) ?? 0) + ct);
    }
  }
  const buckets = [1, 2, 4, 6];
  return buckets.map((v) => ({
    value: v,
    label: v >= 6 ? '6+' : String(v),
    count: grouped.get(v) ?? 0,
  }));
}
