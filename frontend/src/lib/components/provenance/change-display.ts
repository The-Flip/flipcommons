import type { ClaimDisplayValueSchema, ClaimValueSchema, FieldChangeSchema } from '$lib/api/schema';

type FieldChange = FieldChangeSchema;

/** A `ClaimValueSchema` whose `raw` payload is known to be a string. */
type StringClaimValue = Omit<ClaimValueSchema, 'raw'> & {
  raw: string;
  display?: ClaimDisplayValueSchema | null;
};

/**
 * True when both old and new values are strings and at least one exceeds
 * 80 characters, meaning the change should render as an InlineDiff rather
 * than a simple old → new display. Operates on `.raw` since long-string
 * diffs only make sense for direct-field scalars (no display struct).
 *
 * Type guard: inside an `isDiffable(change)` branch, callers get
 * `change.old_value.raw` and `change.new_value.raw` narrowed to `string`
 * without needing an `as string` cast.
 */
export function isDiffable(
  change: FieldChange,
): change is FieldChange & { old_value: StringClaimValue; new_value: StringClaimValue } {
  const oldRaw = change.old_value?.raw;
  const newRaw = change.new_value.raw;
  return (
    typeof oldRaw === 'string' &&
    typeof newRaw === 'string' &&
    (oldRaw.length > 80 || newRaw.length > 80)
  );
}

/**
 * True when a change asserts the same value that already existed — e.g. a
 * second ingest source confirming the canonical value. Such rows should
 * render as a single value, not as an old → new transition.
 */
export function isUnchanged(change: FieldChange): boolean {
  // Normalize "no prior" (old_value bundle is null) and "prior was JSON null"
  // (old_value.raw is null) to the same nothing-asserted state. The wire
  // format doesn't distinguish them, and UX-wise rendering "—> null" as a
  // creation row would be noise: there's no observable difference between
  // "field didn't exist before" and "field was null before" when the new
  // value is also null. If we later want creation-of-null to read as a
  // distinct event (e.g. for ingest provenance), tighten this here.
  const oldRaw = change.old_value?.raw ?? null;
  const newRaw = change.new_value.raw ?? null;
  if (oldRaw === newRaw) return true;
  if (oldRaw == null || newRaw == null) return false;
  return JSON.stringify(oldRaw) === JSON.stringify(newRaw);
}

/**
 * True when a claim value represents an actual assertion — i.e. not null,
 * undefined, empty string, or a bare retraction marker like `{exists: false}`
 * with no other keys. Used to decide whether to render an `old → new`
 * transition or treat the change as a creation / deletion.
 */
export function hasMeaningfulValue(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return false;
  if (typeof v === 'object' && !Array.isArray(v)) {
    const obj = v as Record<string, unknown>;
    if (obj.exists === false) {
      const otherKeys = Object.keys(obj).filter((k) => k !== 'exists');
      if (otherKeys.length === 0) return false;
    }
  }
  return true;
}

/**
 * True when a change deletes a value — old asserted something, new asserts
 * nothing. These render as just the struck-through old value with a removed
 * indicator, not as `old → —`.
 */
export function isDeletion(change: FieldChange): boolean {
  return hasMeaningfulValue(change.old_value?.raw) && !hasMeaningfulValue(change.new_value.raw);
}

/**
 * Defensive fallback: extract a single-string-key claim dict
 * (`{exists: bool, <key>: string}`) into `{display, exists}` so the caller
 * can render `DW` (or struck-through `DW` when `exists` is false) instead
 * of raw JSON.
 *
 * Primarily a safety net for claim values whose namespace isn't registered
 * with a `RelationshipSchema` — those don't get a `display` struct from
 * the backend, so `ClaimValue.svelte` falls through to this. In steady
 * state every registered namespace produces a `display`, making this path
 * rarely exercised; keep it for resilience.
 */
export function simplifyClaimValue(v: unknown): { display: string; exists: boolean } | null {
  if (v === null || typeof v !== 'object' || Array.isArray(v)) return null;
  const obj = v as Record<string, unknown>;
  if (typeof obj.exists !== 'boolean') return null;
  const otherKeys = Object.keys(obj).filter((k) => k !== 'exists');
  if (otherKeys.length !== 1) return null;
  const scalar = obj[otherKeys[0]];
  if (typeof scalar !== 'string') return null;
  return { display: scalar, exists: obj.exists };
}

/**
 * Format an unknown claim value as a plain string. Null/undefined/empty
 * collapse to em-dash; non-strings are JSON-serialized. No truncation:
 * callers control overflow via container CSS (ellipsis vs. wrap), so the
 * full value reaches the DOM and is available for copy/paste and a11y.
 */
export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  return typeof v === 'string' ? v : JSON.stringify(v);
}
