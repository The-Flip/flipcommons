<script lang="ts">
  import { tick } from 'svelte';
  import CitationTooltip from './CitationTooltip.svelte';
  import ReferencesSection from './ReferencesSection.svelte';
  import Prose from '$lib/components/ui/Prose.svelte';
  import type { InlineCitation } from './citation-tooltip';
  import { findRefEntry, findFirstInlineMarker, scrollToAndFlash } from './citation-refs';

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
  let highlightedRef: number | null = $state(null);

  async function scrollToRef(index: number) {
    refsOpen = true;
    // Clear first so a repeat jump to the entry already highlighted replays
    // the flash.
    highlightedRef = null;
    await tick();
    highlightedRef = index;
    await tick();
    if (refsSection) {
      const entry = findRefEntry(refsSection, index);
      entry?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  function scrollToInlineMarker(index: number) {
    if (container) {
      const marker = findFirstInlineMarker(container, index);
      // Imperative here and only here: the marker lives inside `{@html}`, so
      // no component renders it and no scoped class can reach it.
      if (marker) scrollToAndFlash(marker);
    }
  }
</script>

<Prose density="tight">
  <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitized server-side by nh3 -->
  <div class="content" bind:this={container}>{@html html}</div>
</Prose>
<CitationTooltip
  {container}
  contentSignal={html}
  {citations}
  onNavigate={onNavigateToRef ?? (citations && citations.length > 0 ? scrollToRef : undefined)}
/>
{#if showReferences && citations && citations.length > 0}
  <div bind:this={refsSection}>
    <ReferencesSection
      {citations}
      bind:open={refsOpen}
      onBackLink={scrollToInlineMarker}
      highlightedIndex={highlightedRef}
      onFlashEnd={() => (highlightedRef = null)}
    />
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

  /* The markers are inside `{@html}`, so Svelte never sees them and cannot
     hash a class onto them. Scoping to `.content` — a subtree this component
     owns — is the narrowest reach that still matches them. */
  .content :global(.cite-flash) {
    animation: cite-flash 1.5s ease-out;
  }

  /* Scoped per component: `no-unknown-animations` resolves keyframes within a
     stylesheet, so a shared global one would not satisfy it — and Svelte hashes
     a local @keyframes together with the rule referencing it. */
  @keyframes cite-flash {
    from {
      background-color: var(--color-highlight-bg);
    }

    to {
      background-color: transparent;
    }
  }
</style>
