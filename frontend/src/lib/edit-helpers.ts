/**
 * Shared pure helpers for edit-page change detection.
 *
 * No Svelte imports — plain comparisons used by entity-specific
 * build*PatchBody functions.
 */

/**
 * Generic scalar field diff.  Compares each key by string coercion,
 * treats NaN and '' as equivalent, and maps '' → null for cleared fields.
 */
export function diffScalarFields<T extends Record<string, unknown>>(
  current: T,
  original: T,
): Record<string, unknown> {
  const changed: Record<string, unknown> = {};
  for (const key of Object.keys(current) as (keyof T & string)[]) {
    let val: unknown = current[key];
    if (typeof val === 'number' && isNaN(val)) val = '';
    if (String(val) !== String(original[key])) {
      changed[key] = val === '' ? null : val;
    }
  }
  return changed;
}

/**
 * Compare a current public_id array against an original array of {public_id} objects.
 * Order-independent (both sides sorted before comparison).
 */
export function publicIdSetChanged(current: string[], original: { public_id: string }[]): boolean {
  const a = [...current].sort();
  const b = original.map((o) => o.public_id).sort();
  return JSON.stringify(a) !== JSON.stringify(b);
}

/**
 * Compare two string arrays, order-independent.
 * Used for aliases, abbreviations, and similar string lists.
 */
export function stringSetChanged(current: string[], original: string[]): boolean {
  const a = [...current].sort();
  const b = [...original].sort();
  return JSON.stringify(a) !== JSON.stringify(b);
}

/**
 * Compare credit rows (person_slug + role pairs) against an original list.
 * Filters out incomplete rows from `current` before comparing.
 * Order-independent (both sides sorted before comparison).
 */
export function creditsChanged(
  current: { person_slug: string; role: string }[],
  original: { person: { public_id: string }; role: string }[],
): boolean {
  const orig = original.map((c) => `${c.person.public_id}:${c.role}`).sort();
  const curr = current
    .filter((c) => c.person_slug && c.role)
    .map((c) => `${c.person_slug}:${c.role}`)
    .sort();
  return JSON.stringify(orig) !== JSON.stringify(curr);
}
