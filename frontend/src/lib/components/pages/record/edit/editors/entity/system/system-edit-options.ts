/**
 * Cached fetchers for system edit dropdowns (manufacturer, technology subgeneration).
 *
 * Parallel to title-edit-options.ts. Each list is cached per-session.
 */

import client from '$lib/api/client';

export type SystemEditOption = {
  value: string;
  label: string;
  count: number;
};

let cachedManufacturers: Promise<SystemEditOption[]> | null = null;
let cachedTechSubgens: Promise<SystemEditOption[]> | null = null;

export function fetchManufacturerOptions(): Promise<SystemEditOption[]> {
  if (!cachedManufacturers) {
    cachedManufacturers = client
      .GET('/api/manufacturers/all/')
      .then(({ data }) =>
        (data ?? []).map((m) => ({ value: m.slug, label: m.name, count: m.model_count })),
      )
      .catch(() => {
        cachedManufacturers = null;
        return [];
      });
  }
  return cachedManufacturers;
}

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
