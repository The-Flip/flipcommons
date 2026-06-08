/**
 * Shared helper for fetching model edit options.
 *
 * Used by section editors that need dropdown options (people, roles,
 * taxonomy terms, etc.). Eliminates duplicated fetch + type boilerplate.
 */

import client from '$lib/api/client';
import type { EditOptionSchema, ModelEditOptionsSchema } from '$lib/api/schema';

export type ModelEditOptions = ModelEditOptionsSchema;

/**
 * Map backend `{slug, label}` edit options onto the `{value, label}` shape the
 * generic SearchableSelect takes.
 */
export function toSelectOptions(opts: EditOptionSchema[]): { value: string; label: string }[] {
  return opts.map((o) => ({ value: o.slug, label: o.label }));
}

export const EMPTY_EDIT_OPTIONS: ModelEditOptions = {
  tags: [],
  reward_types: [],
  technology_generations: [],
  technology_subgenerations: [],
  display_types: [],
  display_subtypes: [],
  cabinets: [],
  game_formats: [],
  production_statuses: [],
  systems: [],
  credit_roles: [],
};

let cached: Promise<ModelEditOptions> | null = null;

/** Fetch model edit options (cached for the session). */
export function fetchModelEditOptions(): Promise<ModelEditOptions> {
  if (!cached) {
    cached = client
      .GET('/api/models/edit-options/')
      .then(({ data }) => data ?? EMPTY_EDIT_OPTIONS)
      .catch(() => {
        cached = null;
        return EMPTY_EDIT_OPTIONS;
      });
  }
  return cached;
}
