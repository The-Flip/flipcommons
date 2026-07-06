/**
 * Draft state for pending inline citations — `[[cite:slug]]` markers whose
 * `CitationInstance` doesn't exist yet.
 *
 * The editor reserves a slug from the backend the moment the citation picker
 * completes, inserts the marker, and keeps the content spec (source, locator,
 * quote) here, editable until save. The save payload carries the specs in
 * `inline_citations`; the backend mints each instance under its reserved slug
 * in the save transaction. This map is load-bearing editor state: if drafts
 * are ever persisted (autosave, recovery), it must persist with the markdown
 * or recovered drafts have dangling markers.
 */

import type { InlineCitationSpecSchema } from '$lib/api/schema';
import client from '$lib/api/client';
import { extractCiteSlugs } from '$lib/components/provenance/cite-markers';

/** The content spec behind one pending `[[cite:slug]]` marker, plus the
 * source name for display and the source type (which keys the editing
 * panel's locator field into the per-type metadata — label, help, grammar).
 * Locator and quote stay editable until save. */
export type PendingInlineCitation = {
  slug: string;
  sourceId: number;
  sourceName: string;
  sourceType: string;
  locator: string;
  quote: string;
};

/** Reserve a fresh citation slug for a pending inline cite. Throws when the
 * reservation fails (the caller shows the error in place and the user can
 * retry — no marker is inserted without a reserved slug). */
export async function reserveCitationSlug(): Promise<string> {
  const { data, error } = await client.POST('/api/citation-instances/reservations/', {});
  if (error || !data) {
    throw new Error('Failed to reserve a citation slug.');
  }
  return data.slug;
}

/** The pending citations whose marker still appears in `text`, in document
 * order. Drives both the revisitable editing panel (a row disappears when
 * its marker is deleted from the text) and save-payload pruning (a spec
 * without a marker would be rejected by the backend as unreferenced). */
export function pendingCitationsInText(
  pending: readonly PendingInlineCitation[],
  text: string,
): PendingInlineCitation[] {
  const bySlug = new Map(pending.map((p) => [p.slug, p]));
  return extractCiteSlugs(text)
    .map((slug) => bySlug.get(slug))
    .filter((p): p is PendingInlineCitation => p !== undefined);
}

/** Build the save payload's `inline_citations` list: the wire-shape specs of
 * the pending cites whose marker survives in `text`. */
export function buildInlineCitationsRequest(
  pending: readonly PendingInlineCitation[],
  text: string,
): InlineCitationSpecSchema[] {
  return pendingCitationsInText(pending, text).map((p) => ({
    slug: p.slug,
    citation_source_id: p.sourceId,
    locator: p.locator,
    quote: p.quote,
  }));
}
