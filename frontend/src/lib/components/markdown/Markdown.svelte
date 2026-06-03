<script lang="ts">
  import { tick } from 'svelte';
  import CitationTooltip from './CitationTooltip.svelte';
  import ReferencesSection from './ReferencesSection.svelte';
  import Prose from '$lib/components/ui/Prose.svelte';
  import type { InlineCitation } from './citation-tooltip';
  import { findRefEntry, findFirstInlineMarker, scrollToAndHighlight } from './citation-refs';

  let {
    html,
    citations = undefined,
    showReferences = true,
    onNavigateToRef = undefined,
  }: {
    html: string;
    citations?: InlineCitation[];
    showReferences?: boolean;
    onNavigateToRef?: (index: number) => void;
  } = $props();

  let container: HTMLDivElement | undefined = $state();
  let refsSection: HTMLElement | undefined = $state();
  let refsOpen = $state(false);

  async function scrollToRef(index: number) {
    refsOpen = true;
    await tick();
    if (refsSection) {
      const entry = findRefEntry(refsSection, index);
      if (entry) scrollToAndHighlight(entry);
    }
  }

  function scrollToInlineMarker(index: number) {
    if (container) {
      const marker = findFirstInlineMarker(container, index);
      if (marker) scrollToAndHighlight(marker);
    }
  }
</script>

<Prose density="tight">
  <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitized server-side by nh3 -->
  <div class="content" bind:this={container}>{@html html}</div>
</Prose>
<CitationTooltip
  {container}
  htmlSignal={html}
  {citations}
  onNavigate={onNavigateToRef ?? (citations && citations.length > 0 ? scrollToRef : undefined)}
/>
{#if showReferences && citations && citations.length > 0}
  <div bind:this={refsSection}>
    <ReferencesSection {citations} bind:open={refsOpen} onBackLink={scrollToInlineMarker} />
  </div>
{/if}

<style>
  .content :global(.task-list-item) {
    list-style: none;
  }

  .content :global(.task-list-item input[type='checkbox']) {
    margin-right: var(--size-1);
  }

  .content :global(sup[data-cite-id]) {
    cursor: pointer;
    color: var(--color-link);
  }

  .content :global(sup[data-cite-id]:hover),
  .content :global(sup[data-cite-id]:focus-visible) {
    text-decoration: underline;
    outline: none;
  }

  .content :global(.cite-highlight),
  :global(.cite-highlight) {
    background-color: var(--color-highlight-bg);
    transition: background-color 1.5s ease-out;
  }
</style>
