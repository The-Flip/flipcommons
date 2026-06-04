/**
 * API client for the generic entity-autocomplete endpoint.
 *
 * One typeahead over `GET /api/entity-autocomplete/`, keyed by the entity
 * `type` (the registry key — `manufacturer`, `title`, `corporate-entity`, …).
 * The reusable unit any combobox or typeahead can call directly.
 */

import client from './client';
import type { EntityAutocompleteResultSchema } from './schema';

/** One autocomplete row: `value` is the identity string to save, `label`/`sublabel` are display. */
export type EntityOption = EntityAutocompleteResultSchema;

/**
 * Search a registered entity `type` for rows matching `q`.
 *
 * An empty `q` returns the ordered top-N so a freshly-focused control isn't
 * blank. Throws on a non-2xx response (e.g. an unknown `type` → 400).
 */
export async function autocompleteEntities(type: string, q: string): Promise<EntityOption[]> {
  const { data, error, response } = await client.GET('/api/entity-autocomplete/', {
    params: { query: { type, q } },
  });
  // Read status before the guard: this endpoint declares no error response, so
  // `error` is typed `never` and narrowing inside the guard would make
  // `response` unreachable (matches the searchLinkTargets pattern).
  const status = response.status;
  if (error || !data) {
    throw new Error(`Failed to autocomplete ${type}: ${status}`);
  }
  return data.results;
}
