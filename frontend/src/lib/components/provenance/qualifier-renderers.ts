/**
 * Per-qualifier-key rendering for relationship-claim display values.
 *
 * The backend emits structured `ClaimDisplayQualifierPartSchema` entries
 * with `{key, value}`; this module turns each into a string fragment to
 * append to the identity rendering. Keying on the qualifier `ValueKeySpec`
 * name (`count`, `category`, `is_primary`) — not on the namespace — means
 * any future relationship that happens to carry one of these qualifiers
 * gets the same rendering for free.
 */

export type QualifierValue = boolean | number | string | null | undefined;
export type QualifierRenderer = (value: QualifierValue) => string;

export const qualifierRenderers: Record<string, QualifierRenderer> = {
  count: (v) => (typeof v === 'number' && v > 1 ? ` ×${v}` : ''),
  category: (v) => (v ? ` (${v})` : ''),
  is_primary: (v) => (v === true ? ' [primary]' : ''),
};

/**
 * Default rendering for qualifier keys the frontend hasn't been taught
 * about. Mirrors `category`'s truthiness skip (null/false/empty → omit)
 * so unknown data with no visible payload silently disappears.
 */
export function renderDefaultQualifier(key: string, value: QualifierValue): string {
  if (value === null || value === undefined || value === false || value === '') return '';
  return ` (${key}: ${value})`;
}

const warnedKeys = new Set<string>();

/**
 * Render one qualifier entry. Unknown keys go through `renderDefaultQualifier`
 * and emit a one-shot `console.warn` per key — the chip still shows the data
 * (edit history's whole job is transparency about what changed) and the
 * dev-team alert flags the missing rendering rule.
 */
export function renderQualifier(key: string, value: QualifierValue): string {
  const renderer = qualifierRenderers[key];
  if (renderer) return renderer(value);
  if (!warnedKeys.has(key)) {
    warnedKeys.add(key);
    console.warn(`[ClaimValue] No qualifier renderer registered for key "${key}"`);
  }
  return renderDefaultQualifier(key, value);
}

/** Test-only: reset the once-per-key warn dedupe. */
export function _resetQualifierWarnings(): void {
  warnedKeys.clear();
}
