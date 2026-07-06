/**
 * Pure helpers for inline `[[cite:slug]]` markers in edit-history claim text.
 *
 * Edit history shows markdown claim values as authoring-form plain text (the
 * diff operates on it), so inline citations arrive as literal `[[cite:slug]]`
 * tokens. These helpers assign each cited slug a per-change footnote number,
 * rewrite the tokens to compact `[n]` markers *before* the text is diffed
 * (same slug → same marker on both sides, so unchanged citations diff as
 * unchanged), and split marked text for superscript rendering.
 */

import type { FieldChangeSchema } from '$lib/api/schema';
import { diffText } from './change-display';

/**
 * Authoring-form inline citation token. Mirrors the backend's authoring
 * pattern for the `cite` wikilink type: `[[cite:<slug>]]` where the slug is
 * never the `id:` storage prefix (storage-form tokens are left untouched —
 * they only survive to display text when the instance row is gone, and render
 * as-is, matching the editor's broken-link degrade).
 */
const CITE_TOKEN = /\[\[cite:(?!id:)([^\]]+)\]\]/g;

/** A cite marker rewritten by {@link substituteCiteMarkers}: `[1]`, `[2]`, or
 *  `[?]` for a slug with no citation metadata. */
const CITE_MARKER = /^\[(?:\d+|\?)\]$/;

/** {@link CITE_MARKER} as a capturing split pattern, so `String.split` keeps
 *  the markers in the output. */
const CITE_MARKER_SPLIT = /(\[(?:\d+|\?)\])/g;

/** Slugs referenced by `[[cite:slug]]` tokens in `text`, in document order,
 *  deduped keeping the first occurrence. */
export function extractCiteSlugs(text: string): string[] {
  const seen = new Set<string>();
  const slugs: string[] = [];
  for (const match of text.matchAll(CITE_TOKEN)) {
    const slug = match[1];
    if (!seen.has(slug)) {
      seen.add(slug);
      slugs.push(slug);
    }
  }
  return slugs;
}

/**
 * Assign 1-based footnote numbers to the cited slugs of one field change.
 *
 * Numbering follows first appearance in the new text, then slugs only the
 * old text cites (removed by the change) continue the sequence. Only slugs
 * in `knownSlugs` (i.e. with citation metadata to show in the footer) get a
 * number; unknown tokens later render as `[?]`.
 */
export function assignCiteIndexes(
  newText: string,
  oldText: string,
  knownSlugs: ReadonlySet<string>,
): Map<string, number> {
  const indexes = new Map<string, number>();
  for (const slug of [...extractCiteSlugs(newText), ...extractCiteSlugs(oldText)]) {
    if (knownSlugs.has(slug) && !indexes.has(slug)) {
      indexes.set(slug, indexes.size + 1);
    }
  }
  return indexes;
}

/**
 * Footnote numbers for one field change's inline citations, keyed by
 * citation-instance slug — assigned from marker order in the change's own
 * old/new text, so the `[n]` markers and the citations footer agree.
 */
export function citeIndexesForChange(change: FieldChangeSchema): Map<string, number> {
  const known = new Set<string>();
  for (const citation of change.citations ?? []) {
    if (citation.slug != null) known.add(citation.slug);
  }
  return assignCiteIndexes(diffText(change.new_value), diffText(change.old_value), known);
}

/** Rewrite `[[cite:slug]]` tokens in `text` to `[n]` markers (or `[?]` when
 *  the slug has no assigned number). Run on both sides before diffing. */
export function substituteCiteMarkers(text: string, indexes: Map<string, number>): string {
  return text.replace(CITE_TOKEN, (_token, slug: string) => {
    const index = indexes.get(slug);
    return index === undefined ? '[?]' : `[${index}]`;
  });
}

/** One piece of marker-split text: a plain-text run or a `[n]` marker. */
export interface CiteMarkedPart {
  type: 'text' | 'marker';
  text: string;
}

/**
 * Split substituted text into plain runs and `[n]` / `[?]` markers so the
 * markers can render as superscripts. Only apply to text that actually went
 * through {@link substituteCiteMarkers} — on arbitrary prose a literal
 * bracketed number would be misread as a marker.
 */
export function splitCiteMarkers(text: string): CiteMarkedPart[] {
  return text
    .split(CITE_MARKER_SPLIT)
    .filter((piece) => piece !== '')
    .map((piece) => ({
      type: CITE_MARKER.test(piece) ? ('marker' as const) : ('text' as const),
      text: piece,
    }));
}
