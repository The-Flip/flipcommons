import { tick } from 'svelte';
import { findFirstInlineMarker, findRefEntry, scrollToAndFlash } from './citation-refs';

/**
 * Shared state connecting a Rich-Text Overview accordion to its References
 * accordion when they're rendered in separate places on the page. The caller
 * creates one state instance and passes it to both components so the
 * citation back-links and [n] tooltips can scroll between them.
 */
export function createRichTextAccordionState() {
  let descriptionContentEl = $state<HTMLDivElement | undefined>();
  let refsContentEl = $state<HTMLDivElement | undefined>();
  let refsAccordionOpen = $state(false);
  let highlightedRefIndex = $state<number | null>(null);

  function scrollToInlineMarker(index: number) {
    if (!descriptionContentEl) return;
    const marker = findFirstInlineMarker(descriptionContentEl, index);
    // Imperative: the marker is inside `{@html}` markdown, so no component
    // renders it and no scoped class can reach it. Reference entries are
    // component-rendered and flash off `highlightedRefIndex` instead.
    if (marker) scrollToAndFlash(marker);
  }

  async function scrollToRefEntry(index: number) {
    refsAccordionOpen = true;
    // Clear first so a repeat jump to the same entry replays the flash.
    highlightedRefIndex = null;
    await tick();
    highlightedRefIndex = index;
    await tick();
    if (!refsContentEl) return;
    findRefEntry(refsContentEl, index)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  return {
    get descriptionContentEl() {
      return descriptionContentEl;
    },
    set descriptionContentEl(value) {
      descriptionContentEl = value;
    },
    get refsContentEl() {
      return refsContentEl;
    },
    set refsContentEl(value) {
      refsContentEl = value;
    },
    get refsAccordionOpen() {
      return refsAccordionOpen;
    },
    set refsAccordionOpen(value) {
      refsAccordionOpen = value;
    },
    get highlightedRefIndex() {
      return highlightedRefIndex;
    },
    clearHighlightedRef() {
      highlightedRefIndex = null;
    },
    scrollToInlineMarker,
    scrollToRefEntry,
  };
}

export type RichTextAccordionState = ReturnType<typeof createRichTextAccordionState>;
