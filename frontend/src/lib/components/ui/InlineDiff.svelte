<script lang="ts">
  import { computeWordDiff } from '$lib/diff';

  let { oldValue, newValue }: { oldValue: string; newValue: string } = $props();

  let segments = $derived(computeWordDiff(oldValue, newValue));

  let container: HTMLDivElement | undefined = $state();
  let expanded = $state(false);
  let needsExpansion = $state(false);

  const COLLAPSED_HEIGHT = 200;

  $effect(() => {
    // Read segments.length to re-fire when diff content changes.
    void segments.length;
    if (container) {
      needsExpansion = container.scrollHeight > COLLAPSED_HEIGHT;
    }
  });
</script>

<div class="diff-container" class:collapsed={needsExpansion && !expanded} bind:this={container}>
  {#each segments as seg, i (i)}
    {#if seg.type === 'added'}
      <ins>{seg.text}</ins>
    {:else if seg.type === 'removed'}
      <del>{seg.text}</del>
    {:else}
      <span>{seg.text}</span>
    {/if}
  {/each}
</div>
{#if needsExpansion}
  <button class="diff-toggle" onclick={() => (expanded = !expanded)}>
    {expanded ? 'Show less' : 'Show full diff'}
  </button>
{/if}

<style>
  .diff-container {
    font-size: var(--font-size-0);
    line-height: var(--font-lineheight-3);
    overflow-wrap: break-word;
    white-space: pre-wrap;
  }

  .collapsed {
    max-height: 200px;
    overflow: hidden;
    /* `black` here is a luminance alpha for the mask, not a theme color. */
    /* stylelint-disable-next-line color-named */
    mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
    /* stylelint-disable-next-line color-named */
    -webkit-mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
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

  .diff-toggle {
    background: none;
    border: none;
    color: var(--color-link);
    font-size: var(--font-size-0);
    padding: var(--size-1) 0 0;
    cursor: pointer;
  }

  .diff-toggle:hover {
    text-decoration: underline;
  }
</style>
