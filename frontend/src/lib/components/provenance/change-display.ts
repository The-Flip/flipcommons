import type {
  ClaimDisplayIdentityPartSchema,
  ClaimDisplayValueSchema,
  ClaimValueSchema,
  FieldChangeSchema,
} from '$lib/api/schema';
import { DELETED_PLACEHOLDER, MISSING_PLACEHOLDER } from './claim-display';

type FieldChange = FieldChangeSchema;

/** One member of an object-valued claim, ready for member-level diff rendering. */
export interface StructuredDiffPart {
  key: string;
  label: string;
  oldText: string | null;
  newText: string;
  changed: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function valuesEqual(oldValue: unknown, newValue: unknown): boolean {
  if (oldValue === newValue) return true;
  if (oldValue == null || newValue == null) return false;
  return JSON.stringify(oldValue) === JSON.stringify(newValue);
}

function humanizeKey(key: string): string {
  const words = key.replaceAll('_', ' ').replaceAll('-', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function humanizeRelationshipValue(value: unknown): string {
  if (typeof value !== 'string') return formatValue(value);
  if (!/^[a-z0-9_-]+$/.test(value)) return value;
  return humanizeKey(value);
}

function identityText(part: ClaimDisplayIdentityPartSchema | undefined): string {
  if (!part) return '—';
  if (part.state === 'deleted') return DELETED_PLACEHOLDER;
  if (part.state === 'missing') return MISSING_PLACEHOLDER;
  return part.label ?? '—';
}

/** Object keys that carry displayable content — everything but the `exists` marker. */
function contentKeys(raw: Record<string, unknown>): string[] {
  return Object.keys(raw).filter((key) => key !== 'exists');
}

/**
 * Build parts for a plain key set, deriving each cell from `resolve`. Shared by
 * the raw-JSON branches whose members are keyed but carry no backend labels.
 */
function partsForKeys(
  keys: string[],
  resolve: (key: string) => Pick<StructuredDiffPart, 'oldText' | 'newText' | 'changed'>,
): StructuredDiffPart[] {
  return keys.map((key) => ({ key, label: humanizeKey(key), ...resolve(key) }));
}

function relationshipDisplay(
  value: ClaimValueSchema | null | undefined,
): ClaimDisplayValueSchema | null {
  return value?.display?.kind === 'relationship' ? value.display : null;
}

function orderedUnion(first: string[], second: string[]): string[] {
  return [...new Set([...first, ...second])];
}

function buildRelationshipDiff(
  oldRaw: Record<string, unknown>,
  newRaw: Record<string, unknown>,
  oldDisplay: ClaimDisplayValueSchema,
  newDisplay: ClaimDisplayValueSchema,
): StructuredDiffPart[] {
  const identityKeys = orderedUnion(
    oldDisplay.identity.map((part) => part.key),
    newDisplay.identity.map((part) => part.key),
  );
  const qualifierKeys = orderedUnion(
    oldDisplay.qualifiers.map((part) => part.key),
    newDisplay.qualifiers.map((part) => part.key),
  );

  const identityParts = identityKeys.map((key) => {
    const oldPart = oldDisplay.identity.find((part) => part.key === key);
    const newPart = newDisplay.identity.find((part) => part.key === key);
    const oldText = identityText(oldPart);
    const newText = identityText(newPart);
    return {
      key,
      label: humanizeKey(key),
      oldText,
      newText,
      changed: oldText !== newText || !valuesEqual(oldRaw[key], newRaw[key]),
    };
  });

  const qualifierParts = qualifierKeys.map((key) => {
    const oldPart = oldDisplay.qualifiers.find((part) => part.key === key);
    const newPart = newDisplay.qualifiers.find((part) => part.key === key);
    const oldValue = oldPart?.value;
    const newValue = newPart?.value;
    return {
      key,
      label: humanizeKey(key),
      oldText: humanizeRelationshipValue(oldValue),
      newText: humanizeRelationshipValue(newValue),
      changed: !valuesEqual(oldValue, newValue),
    };
  });

  return [...identityParts, ...qualifierParts];
}

function buildRelationshipCreation(newDisplay: ClaimDisplayValueSchema): StructuredDiffPart[] {
  const identityParts = newDisplay.identity.map((part) => ({
    key: part.key,
    label: humanizeKey(part.key),
    oldText: null,
    newText: identityText(part),
    changed: true,
  }));
  const qualifierParts = newDisplay.qualifiers.map((part) => ({
    key: part.key,
    label: humanizeKey(part.key),
    oldText: null,
    newText: humanizeRelationshipValue(part.value),
    changed: true,
  }));
  return [...identityParts, ...qualifierParts];
}

/**
 * Build a member-level diff for object-valued claims. Relationship claims use
 * their backend-provided identity labels and qualifier order; unknown JSON
 * objects fall back to their raw keys. Creations, deletions, and tombstones
 * retain the ordinary whole-value rendering because their existence changed.
 */
export function buildStructuredDiff(change: FieldChange): StructuredDiffPart[] | null {
  const oldRaw = change.old_value?.raw;
  const newRaw = change.new_value.raw;
  if (!isRecord(newRaw) || newRaw.exists === false) return null;

  const oldDisplay = relationshipDisplay(change.old_value);
  const newDisplay = relationshipDisplay(change.new_value);
  if (oldRaw == null) {
    if (newDisplay) {
      const parts = buildRelationshipCreation(newDisplay);
      return parts.length > 0 ? parts : null;
    }
    const keys = contentKeys(newRaw);
    if (keys.length === 0) return null;
    return partsForKeys(keys, (key) => ({
      oldText: null,
      newText: formatValue(newRaw[key]),
      changed: true,
    }));
  }

  if (!isRecord(oldRaw) || oldRaw.exists === false) return null;
  if (oldDisplay && newDisplay) {
    const parts = buildRelationshipDiff(oldRaw, newRaw, oldDisplay, newDisplay);
    return parts.length > 0 ? parts : null;
  }

  const keys = orderedUnion(contentKeys(oldRaw), contentKeys(newRaw));
  if (keys.length === 0) return null;
  return partsForKeys(keys, (key) => ({
    oldText: formatValue(oldRaw[key]),
    newText: formatValue(newRaw[key]),
    changed: !valuesEqual(oldRaw[key], newRaw[key]),
  }));
}

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
  return valuesEqual(oldRaw, newRaw);
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
 * How a field change should render, decided once. Most-specific-first:
 * unchanged → deletion → text diff → member-level structured diff → scalar
 * old→new. `structuredDiff` carries its already-built parts so callers don't
 * recompute. Views that don't distinguish every mode (the changelog feed, the
 * retracted-row branch) fold the ones they skip into their scalar rendering.
 */
export type ChangeRenderMode =
  | { kind: 'unchanged' }
  | { kind: 'deletion' }
  | { kind: 'textDiff' }
  | { kind: 'structuredDiff'; parts: StructuredDiffPart[] }
  | { kind: 'scalar' };

/** Classify a change into its render mode; the single source of that decision. */
export function classifyChange(change: FieldChange): ChangeRenderMode {
  if (isUnchanged(change)) return { kind: 'unchanged' };
  if (isDeletion(change)) return { kind: 'deletion' };
  if (isDiffable(change)) return { kind: 'textDiff' };
  const parts = buildStructuredDiff(change);
  if (parts) return { kind: 'structuredDiff', parts };
  return { kind: 'scalar' };
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
