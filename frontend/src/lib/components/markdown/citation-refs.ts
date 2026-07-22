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
 *
 * Matches on the data attribute alone: markers are a `<sup>` in server-rendered
 * markdown and a `<button>` where a component renders them, so qualifying the
 * selector by tag would miss one surface or the other.
 */
export function findFirstInlineMarker(container: Element, index: number): Element | null {
  return container.querySelector(`[data-cite-index="${index}"]`);
}

/**
 * Class driving the `cite-flash` keyframe (declared in `app.css`).
 *
 * Only for elements no component owns — the `sup` markers inside
 * server-rendered markdown, which Svelte cannot attach a scoped class to.
 * Anywhere a component renders the target itself, bind the class declaratively
 * instead so the style stays scoped; see `CitationReference.svelte`.
 */
export const CITE_FLASH_CLASS = 'cite-flash';

/**
 * Smooth-scroll to an element and flash it.
 *
 * Safe to call rapidly: the class is removed and re-added around a forced
 * reflow, so a repeat jump to the same element restarts the animation.
 */
export function scrollToAndFlash(element: Element): void {
  element.scrollIntoView({ behavior: 'smooth', block: 'center' });

  element.classList.remove(CITE_FLASH_CLASS);
  // Forces style recalculation, without which the removal and re-add collapse
  // into no change at all and the animation never restarts. Read through
  // `getBoundingClientRect`, which every Element has, rather than an
  // HTMLElement-only property that would need a cast to reach.
  element.getBoundingClientRect();
  element.classList.add(CITE_FLASH_CLASS);
  element.addEventListener('animationend', () => element.classList.remove(CITE_FLASH_CLASS), {
    once: true,
  });
}
