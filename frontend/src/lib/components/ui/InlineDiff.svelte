<!-- @component A word-level diff of two text values, capped to a few lines
until the reader asks for the rest. -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { computeWordDiff } from '$lib/diff';
  import CollapsibleBlock from './CollapsibleBlock.svelte';

  let {
    oldValue,
    newValue,
    renderText,
  }: {
    oldValue: string;
    newValue: string;
    /** Optional renderer for each diff segment's text, so callers can style
     *  sub-runs (e.g. superscript cite markers) without the diff knowing. */
    renderText?: Snippet<[string]>;
  } = $props();

  let segments = $derived(computeWordDiff(oldValue, newValue));
  let expanded = $state(false);
</script>

{#snippet segText(text: string)}
  {#if renderText}{@render renderText(text)}{:else}{text}{/if}
{/snippet}

<CollapsibleBlock
  expandLabel="Show full diff"
  {expanded}
  onExpandedChange={(next) => (expanded = next)}
  signal={segments.length}
>
  <div class="diff-container">
    {#each segments as seg, i (i)}
      {#if seg.type === 'added'}
        <ins>{@render segText(seg.text)}</ins>
      {:else if seg.type === 'removed'}
        <del>{@render segText(seg.text)}</del>
      {:else}
        <span>{@render segText(seg.text)}</span>
      {/if}
    {/each}
  </div>
</CollapsibleBlock>

<style>
  .diff-container {
    font-size: var(--font-size-0);
    line-height: var(--font-lineheight-3);
    overflow-wrap: break-word;
    white-space: pre-wrap;
  }

  ins {
    background-color: var(--color-diff-ins-bg);
    text-decoration: none;
    border-radius: 2px;
    padding: 0 1px;
  }

  del {
    background-color: var(--color-diff-del-bg);
    text-decoration: line-through;
    border-radius: 2px;
    padding: 0 1px;
    opacity: 0.7;
  }
</style>
