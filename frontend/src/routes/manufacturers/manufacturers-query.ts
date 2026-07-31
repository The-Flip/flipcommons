/**
 * URL → backend query mapping for the SSR /manufacturers page.
 *
 * Kept local to the route (mirrors `games-query.ts`). Because the URL params already
 * use the real `ManufacturerFilterQuery` field names (one vocabulary end to end — see
 * `PARAM_MAP` in `manufacturer-facet-engine`), this is a near passthrough: read each
 * param, coerce numbers. All facets are single-value (no repeated multi-value params).
 */

import { toNum } from '$lib/manufacturer-facet-engine';

/** The `/api/manufacturers/` query object (every filter dimension; `page` added by the caller). */
export interface ManufacturersQuery {
  q?: string;
  location?: string;
  person?: string;
  tech_gen?: string;
  year_min?: number;
  year_max?: number;
}

export function queryFromUrl(url: URL): ManufacturersQuery {
  const sp = url.searchParams;
  const str = (p: string): string | undefined => sp.get(p) || undefined;
  const num = (p: string): number | undefined => {
    const v = sp.get(p);
    if (v == null) return undefined;
    return toNum(v) ?? undefined;
  };

  return {
    q: str('q'),
    location: str('location'),
    person: str('person'),
    tech_gen: str('tech_gen'),
    year_min: num('year_min'),
    year_max: num('year_max'),
  };
}
