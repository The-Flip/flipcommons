/**
 * Cached fetchers for title edit dropdowns (franchise, series).
 *
 * Parallel to model-edit-options.ts. The backend doesn't have a single
 * /api/titles/edit-options/ endpoint yet, so we fetch each list separately
 * and cache per-session.
 */

import client from '$lib/api/client';

export type TitleEditOption = {
  value: string;
  label: string;
  count: number;
};

let cachedFranchises: Promise<TitleEditOption[]> | null = null;
let cachedSeries: Promise<TitleEditOption[]> | null = null;

export function fetchFranchiseOptions(): Promise<TitleEditOption[]> {
  if (!cachedFranchises) {
    cachedFranchises = client
      .GET('/api/franchises/all/')
      .then(({ data }) =>
        (data ?? []).map((f) => ({ value: f.slug, label: f.name, count: f.title_count })),
      )
      .catch(() => {
        cachedFranchises = null;
        return [];
      });
  }
  return cachedFranchises;
}

export function fetchSeriesOptions(): Promise<TitleEditOption[]> {
  if (!cachedSeries) {
    cachedSeries = client
      .GET('/api/series/')
      .then(({ data }) =>
        (data ?? []).map((s) => ({ value: s.slug, label: s.name, count: s.title_count })),
      )
      .catch(() => {
        cachedSeries = null;
        return [];
      });
  }
  return cachedSeries;
}
