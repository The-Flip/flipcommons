/**
 * URL → backend query mapping for the SSR /games page.
 *
 * Kept local to the route (not in a generic harness): people is search-only and
 * manufacturers differ, so we apply the rule of three before extracting. Because
 * the URL params already use the real `GameFilterQuerySchema` field names (one
 * vocabulary end to end — see `PARAM_MAP` in facet-engine), this is a near
 * passthrough: read each param, coerce numbers, read repeated multi-value params
 * with `getAll`.
 */

/** The `/api/games/` query object (every filter dimension; `page` added by the caller). */
export interface GamesQuery {
  q?: string;
  manufacturer?: string;
  person?: string;
  technology_generation?: string;
  display_type?: string;
  system?: string;
  franchise?: string;
  series?: string;
  player_count?: number;
  year_min?: number;
  year_max?: number;
  theme?: string[];
  gameplay_feature?: string[];
  reward_type?: string[];
  edge?: string[];
  game_format?: string[];
  production_status?: string[];
  cabinet?: string[];
}

export function queryFromUrl(url: URL): GamesQuery {
  const sp = url.searchParams;
  const str = (p: string): string | undefined => sp.get(p) || undefined;
  const num = (p: string): number | undefined => {
    const v = sp.get(p);
    if (v == null || v === '') return undefined;
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
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
  };
}
