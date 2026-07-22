<script lang="ts">
  import type { InlineCitation } from './citation-tooltip';
  import { deduplicateCitations } from './citation-refs';
  import CitationReference from './CitationReference.svelte';

  let {
    citations,
    open = $bindable(false),
    onBackLink,
    showToggle = true,
    highlightedIndex = null,
    onFlashEnd,
  }: {
    citations: InlineCitation[];
    open?: boolean;
    onBackLink: (index: number) => void;
    showToggle?: boolean;
    /** Reference number to flash — the entry a marker just jumped to. */
    highlightedIndex?: number | null;
    onFlashEnd?: () => void;
  } = $props();

  let uniqueCitations = $derived(deduplicateCitations(citations));
</script>

<section class="references-section" class:embedded={!showToggle}>
  {#if showToggle}
    <button class="toggle" onclick={() => (open = !open)} aria-expanded={open}>
      References ({uniqueCitations.length})
    </button>
  {/if}
  {#if open || !showToggle}
    <ol>
      {#each uniqueCitations as cite (cite.index)}
        <CitationReference
          index={cite.index}
          citation={cite}
          {onBackLink}
          highlighted={cite.index === highlightedIndex}
          {onFlashEnd}
        />
      {/each}
    </ol>
  {/if}
</section>

<style>
  .references-section {
    margin-top: var(--size-4);
    border-top: 1px solid var(--color-border-soft);
    padding-top: var(--size-2);
  }

  .references-section.embedded {
    margin-top: 0;
    border-top: none;
    padding-top: 0;
  }

  .toggle {
    background: none;
    border: none;
    cursor: pointer;
    font-size: var(--font-size-1);
    font-weight: 600;
    color: var(--color-text-muted);
    padding: var(--size-1) 0;
  }

  .toggle:hover {
    color: var(--color-text);
  }

  ol {
    margin: var(--size-2) 0 0;
    padding-left: var(--size-5);
    font-size: var(--font-size-1);
    line-height: var(--font-lineheight-3);
  }
</style>
