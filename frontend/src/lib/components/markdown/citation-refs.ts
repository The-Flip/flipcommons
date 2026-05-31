/**
 * Pure helpers for citation references: deduplication, mapping, and
 * DOM queries. Extracted so they're testable without Svelte components.
 */

import type { InlineCitation } from './citation-tooltip';

/**
 * Deduplicate citations by index, keeping the first occurrence of each.
 * Used by ReferencesSection to render one entry per unique reference number.
 */
export function deduplicateCitations(citations: InlineCitation[]): InlineCitation[] {
  const seen = new Set<number>();
  const result: InlineCitation[] = [];
  for (const cite of citations) {
    if (!seen.has(cite.index)) {
      seen.add(cite.index);
      result.push(cite);
    }
  }
  return result;
}

/**
 * Build an id → CitationInfo map from the citations array.
 * Used by CitationTooltip to populate its data from props instead of fetching.
 */
export function buildCitationMap(citations: InlineCitation[]): Map<number, InlineCitation> {
  const map = new Map<number, InlineCitation>();
  for (const cite of citations) {
    map.set(cite.id, cite);
  }
  return map;
}

/**
 * Find a reference entry element by its index within a container.
 */
export function findRefEntry(container: Element, index: number): Element | null {
  return container.querySelector(`[data-ref-index="${index}"]`);
}

/**
 * Find the first inline citation marker with a given index within a container.
 */
export function findFirstInlineMarker(container: Element, index: number): Element | null {
  return container.querySelector(`sup[data-cite-index="${index}"]`);
}

const highlightTimers = new WeakMap<Element, ReturnType<typeof setTimeout>>();

/**
 * Smooth-scroll to an element and briefly highlight it.
 * Safe to call rapidly — clears any pending highlight timeout on the
 * same element before starting a new one.
 */
export function scrollToAndHighlight(element: Element): void {
  element.scrollIntoView({ behavior: 'smooth', block: 'center' });

  const existing = highlightTimers.get(element);
  if (existing != null) clearTimeout(existing);

  element.classList.add('cite-highlight');
  highlightTimers.set(
    element,
    setTimeout(() => {
      element.classList.remove('cite-highlight');
      highlightTimers.delete(element);
    }, 1500),
  );
}
