/**
 * Pure helpers for citation references: deduplication, mapping, and
 * DOM queries. Extracted so they're testable without Svelte components.
 */

import type { InlineCitation } from './citation-tooltip';

/**
 * Deduplicate citations by index, keeping the first occurrence of each — one
 * entry per reference number.
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
 * Build an id → citation map from the citations array, for resolving a marker
 * to its citation without a fetch.
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
 *
 * Matches on the data attribute alone: a marker's tag varies with how it was
 * rendered, so qualifying the selector by element would miss some of them.
 */
export function findFirstInlineMarker(container: Element, index: number): Element | null {
  return container.querySelector(`[data-cite-index="${index}"]`);
}

/**
 * Class that plays the flash animation. Only for a target this code applies it
 * to imperatively — where the element is rendered declaratively, bind the class
 * there instead so the rule can stay scoped to it.
 */
export const CITE_FLASH_CLASS = 'cite-flash';

/** Strips the flash class once its animation finishes. Declared once rather
 *  than per call so the listener can be replaced instead of stacked. */
function clearFlash(event: Event): void {
  if (event.currentTarget instanceof Element) {
    event.currentTarget.classList.remove(CITE_FLASH_CLASS);
  }
}

/**
 * Smooth-scroll to an element and flash it.
 *
 * Safe to call rapidly. Restarting the animation means removing and re-adding
 * the class around a forced reflow — without the reflow the pair collapses into
 * no change at all. That removal cancels the running animation, which fires
 * `animationcancel` rather than `animationend`, so the previous listener would
 * never fire and never retire itself; it is dropped explicitly instead.
 */
export function scrollToAndFlash(element: Element): void {
  element.scrollIntoView({ behavior: 'smooth', block: 'center' });

  element.removeEventListener('animationend', clearFlash);
  element.classList.remove(CITE_FLASH_CLASS);
  // Read through `getBoundingClientRect`, which every Element has, rather than
  // an HTMLElement-only property that would need a cast to reach.
  element.getBoundingClientRect();
  element.classList.add(CITE_FLASH_CLASS);
  element.addEventListener('animationend', clearFlash, { once: true });
}
