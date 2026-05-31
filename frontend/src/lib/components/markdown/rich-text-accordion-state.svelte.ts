import { tick } from 'svelte';
import { findFirstInlineMarker, findRefEntry, scrollToAndHighlight } from './citation-refs';

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

  function scrollToInlineMarker(index: number) {
    if (!descriptionContentEl) return;
    const marker = findFirstInlineMarker(descriptionContentEl, index);
    if (marker) scrollToAndHighlight(marker);
  }

  async function scrollToRefEntry(index: number) {
    refsAccordionOpen = true;
    await tick();
    if (!refsContentEl) return;
    const entry = findRefEntry(refsContentEl, index);
    if (entry) scrollToAndHighlight(entry);
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
    scrollToInlineMarker,
    scrollToRefEntry,
  };
}

export type RichTextAccordionState = ReturnType<typeof createRichTextAccordionState>;
