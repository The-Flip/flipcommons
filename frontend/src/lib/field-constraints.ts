/**
 * Fetch numeric field constraints from the backend.
 *
 * The backend derives these from Django model validators, making it the
 * single source of truth for min/max/step on numeric fields.
 */

import client from '$lib/api/client';
import type { CatalogEntityKey } from '$lib/entities/entity-meta';
import type { FieldConstraintSchema } from '$lib/api/schema';

export type FieldConstraints = Record<string, FieldConstraintSchema>;

const cache = new Map<string, FieldConstraints>();

export async function fetchFieldConstraints(
  entityType: CatalogEntityKey,
): Promise<FieldConstraints> {
  const cached = cache.get(entityType);
  if (cached) return cached;

  const { data } = await client.GET('/api/field-constraints/{entity_type}', {
    params: { path: { entity_type: entityType } },
  });

  const constraints: FieldConstraints = data ?? {};
  cache.set(entityType, constraints);
  return constraints;
}

/** Props for spreading into a NumberField: `{...fc(constraints, 'year')}`.
 *
 * Null values from the backend (unbounded min/max) are stripped so the
 * NumberField component sees `undefined` — its props are typed as optional
 * `number`, not `number | null`.
 */
export function fc(
  constraints: FieldConstraints,
  field: string,
): { min?: number; max?: number; step?: number } {
  const c = constraints[field];
  if (!c) return {};
  const out: { min?: number; max?: number; step?: number } = { step: c.step };
  if (c.min != null) out.min = c.min;
  if (c.max != null) out.max = c.max;
  return out;
}
