import type { ClaimValueSchema, FieldChangeSchema } from '$lib/api/schema';

type FieldChange = FieldChangeSchema;

/**
 * The text a claim value contributes to a diff. For markdown fields this is
 * the authoring-form `display.text` (`[[type:slug]]`), so the diff reads the
 * same legible form the editor shows rather than raw `[[type:id:N]]` storage.
 * For everything else it's the raw value coerced to a string.
 */
export function diffText(value: ClaimValueSchema | null | undefined): string {
  if (value?.display?.kind === 'markdown') return value.display.text;
  const raw = value?.raw;
  return typeof raw === 'string' ? raw : '';
}

/**
 * Whether a value contributes string content to a diff: a raw string, or a
 * markdown field whose authoring-form `display.text` we diff. Non-string
 * scalars and relationship dicts don't diff as text.
 */
function diffsAsText(value: ClaimValueSchema | null | undefined): boolean {
  return typeof value?.raw === 'string' || value?.display?.kind === 'markdown';
}

/**
 * True when both old and new values diff as text and at least one exceeds 80
 * characters, meaning the change should render as an InlineDiff rather than a
 * simple old → new display. Thresholds on `diffText`, so markdown fields use
 * their authoring form, not the storage form.
 */
export function isDiffable(change: FieldChange): boolean {
  if (!diffsAsText(change.old_value) || !diffsAsText(change.new_value)) return false;
  return diffText(change.old_value).length > 80 || diffText(change.new_value).length > 80;
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
 * undefined, empty string, or a retraction marker with nothing visible to
 * say: `{exists: false}` bare, or a tombstone whose remaining keys are all
 * null/empty (the narrowed label-slot tombstone, whose wording lives on the
 * chronologically prior claim, surfaced by the backend as `old_value`).
 * Used to decide whether to render an `old → new` transition or treat the
 * change as a creation / deletion.
 */
export function hasMeaningfulValue(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return false;
  if (typeof v === 'object' && !Array.isArray(v)) {
    const obj = v as Record<string, unknown>;
    if (obj.exists === false) {
      const visible = Object.entries(obj).filter(
        ([k, val]) => k !== 'exists' && val !== null && val !== '',
      );
      if (visible.length === 0) return false;
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
