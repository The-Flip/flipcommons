/**
 * Cached fetcher for the system technology-subgeneration dropdown.
 *
 * The manufacturer field (both edit and create flows) moved to the
 * `/api/entity-autocomplete/` typeahead (`EntitySelect`); only the
 * technology-subgeneration list still loads here, cached per-session.
 */

import client from '$lib/api/client';

export type SystemEditOption = {
  value: string;
  label: string;
  count: number;
};

let cachedTechSubgens: Promise<SystemEditOption[]> | null = null;

export function fetchTechnologySubgenerationOptions(): Promise<SystemEditOption[]> {
  if (!cachedTechSubgens) {
    cachedTechSubgens = client
      .GET('/api/technology-generations/')
      .then(({ data }) =>
        (data ?? []).flatMap((g) =>
          g.subgenerations.map((s) => ({ value: s.slug, label: s.name, count: 0 })),
        ),
      )
      .catch(() => {
        cachedTechSubgens = null;
        return [];
      });
  }
  return cachedTechSubgens;
}
