/**
 * Pure data transform: turn a backend `ClaimDisplayValueSchema` into the
 * flat list of segments the renderer iterates over. Kept Svelte-free so
 * the rendering rules — identity-joined-by-em-dash, deleted/missing get
 * placeholder text, qualifiers concatenated at the end — can be covered
 * by unit tests without a DOM.
 */
import type { ClaimDisplayValueSchema } from '$lib/api/schema';
import { renderQualifier } from './qualifier-renderers';

export type DisplaySegment = { text: string; missing: boolean };

// Non-breaking spaces around the em-dash so a long name doesn't wrap
// mid-separator.
export const IDENTITY_SEPARATOR = ' — ';

export const DELETED_PLACEHOLDER = '(deleted)';
export const MISSING_PLACEHOLDER = '(missing)';

export function buildDisplaySegments(display: ClaimDisplayValueSchema): DisplaySegment[] {
  const out: DisplaySegment[] = [];
  display.identity.forEach((part, i) => {
    if (i > 0) out.push({ text: IDENTITY_SEPARATOR, missing: false });
    if (part.state === 'resolved') {
      out.push({ text: part.label ?? '', missing: false });
    } else if (part.state === 'deleted') {
      out.push({ text: DELETED_PLACEHOLDER, missing: true });
    } else {
      out.push({ text: MISSING_PLACEHOLDER, missing: true });
    }
  });
  const qf = display.qualifiers.map((q) => renderQualifier(q.key, q.value)).join('');
  if (qf) out.push({ text: qf, missing: false });
  return out;
}
