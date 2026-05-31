<script lang="ts">
  /**
   * Render a relationship claim's structured display. The segment-building
   * rules live in `claim-display.ts` (pure, unit-tested); this component
   * is only responsible for turning segments into DOM.
   */
  import type { ClaimDisplayValueSchema } from '$lib/api/schema';
  import { buildDisplaySegments } from './claim-display';

  let { display }: { display: ClaimDisplayValueSchema } = $props();

  let segments = $derived(buildDisplaySegments(display));
</script>

<!--
  One-line each body: any whitespace between adjacent iterations (newlines,
  indentation) survives as DOM text nodes and corrupts the rendering. Keep
  everything between `{#each}` and `{/each}` flush.
-->
{#each segments as seg, i (i)}{#if seg.missing}<span class="missing-ref">{seg.text}</span
    >{:else}{seg.text}{/if}{/each}

<style>
  .missing-ref {
    font-style: italic;
    color: var(--color-text-muted);
  }
</style>
