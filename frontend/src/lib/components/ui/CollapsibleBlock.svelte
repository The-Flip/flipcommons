<!-- @component Content capped to a collapsed height, its clipped edge faded so
the cut is visible, with a toggle that appears only when there is something
hidden to reveal. Collapsed is the rendered default, so the full content is
always in the DOM — clipped, never withheld.

Collapse to at least two lines: the fade is what tells a reader the text
continues, and it needs a line to act on that is not the only line shown. -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    children,
    collapsedHeight,
    expandLabel = 'Show more',
    collapseLabel = 'Show less',
    expanded = false,
    onExpandedChange,
    signal,
  }: {
    children: Snippet;
    /** Any CSS length. Omit for the default declared in the style block —
     *  which is where it lives, so the linter can see the property this
     *  overrides rather than treating it as an unknown token. */
    collapsedHeight?: string;
    expandLabel?: string;
    collapseLabel?: string;
    /** Owned by the caller, so a page rendering many of these can keep one
     *  record of which are open and open one itself. */
    expanded?: boolean;
    onExpandedChange?: (expanded: boolean) => void;
    /** Changes when the content may have changed, re-running the measurement. */
    signal?: unknown;
  } = $props();

  let container: HTMLDivElement | undefined = $state();
  let overflows = $state(false);

  $effect(() => {
    void signal;
    // Only while collapsed: expanded, scrollHeight equals clientHeight and the
    // measurement would retract the toggle that got the reader here.
    if (container && !expanded) overflows = container.scrollHeight > container.clientHeight;
  });
</script>

<div
  class="block"
  class:collapsed={!expanded}
  class:fade={overflows && !expanded}
  style:--collapsed-height={collapsedHeight}
  bind:this={container}
>
  {@render children()}
</div>
{#if overflows}
  <button class="toggle" onclick={() => onExpandedChange?.(!expanded)} aria-expanded={expanded}>
    {expanded ? collapseLabel : expandLabel}
  </button>
{/if}

<style>
  .block {
    /* The default cap. The `collapsedHeight` prop overrides it inline, which
       wins over this declaration; declaring it here is also what lets the
       custom-property linter resolve the reference below. */
    --collapsed-height: 200px;
  }

  .collapsed {
    max-height: var(--collapsed-height);
    overflow: hidden;
  }

  .fade {
    /* `black` here is a luminance alpha for the mask, not a theme color. */
    /* stylelint-disable-next-line color-named */
    mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
    /* stylelint-disable-next-line color-named */
    -webkit-mask-image: linear-gradient(to bottom, black 70%, transparent 100%);
  }

  .toggle {
    background: none;
    border: none;
    color: var(--color-link);
    font-size: var(--font-size-0);
    padding: var(--size-1) 0 0;
    cursor: pointer;
  }

  .toggle:hover {
    text-decoration: underline;
  }
</style>
