/**
 * Shape rules for SvelteKit route IDs (`/titles/[slug]/sources`), shared by
 * everything that classifies a route by reading its pattern.
 */

// CONVENTION: every catalog entity's detail param is named `[slug]` (or
// `[...path]` for Location's multi-segment public_id). A new entity using a
// different param name (e.g. `[id]`, `[handle]`) will not be recognized as a
// record route — the fix is to rename the param to `[slug]` or extend this
// regex. The convention keeps every matcher over route IDs trivial.
const PUBLIC_ID_SEGMENT_RE = /^\[(?:slug|\.\.\.path)\]$/;

/**
 * Whether a route-ID segment is the slot holding a record's public id — the
 * `[slug]` in `/titles/[slug]`, the `[...path]` in `/locations/[...path]`.
 */
export function isPublicIdSegment(segment: string): boolean {
  return PUBLIC_ID_SEGMENT_RE.test(segment);
}
