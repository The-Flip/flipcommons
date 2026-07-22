<!-- @component A claim value rendered for reading: markdown values with inline
citations render their [[cite:]] tokens as numbered superscripts, and markdown
keeps its line breaks; everything else falls through to ClaimValue. -->
<script lang="ts">
  import type { ClaimValueSchema } from '$lib/api/schema';
  import ClaimValue from './ClaimValue.svelte';
  import CiteMarkedText from './CiteMarkedText.svelte';
  import { substituteCiteMarkers, type CiteMarkerInteractions } from './cite-markers';

  let {
    value,
    citeIndexes,
    interactions,
  }: {
    value: ClaimValueSchema | null | undefined;
    /** Per-change footnote numbers from `citeIndexesForChange`. */
    citeIndexes: Map<string, number>;
    /** Makes the rendered markers live. Omit on surfaces with no reference
     *  list for them to jump to. */
    interactions?: CiteMarkerInteractions;
  } = $props();
</script>

<!-- Wrapped so the whitespace rule below reaches both branches, and tight
     against the content because `pre-wrap` would render any indentation the
     markup introduced. -->
<span class:markdown={value?.display?.kind === 'markdown'}
  >{#if value?.display?.kind === 'markdown' && citeIndexes.size > 0}<CiteMarkedText
      text={substituteCiteMarkers(value.display.text, citeIndexes)}
      {interactions}
    />{:else}<ClaimValue {value} />{/if}</span
>

<style>
  /* The line breaks an author typed are part of a markdown value, so every
     surface reading one keeps them. Here rather than in each surface's CSS,
     which is how the Sources page came to collapse them while edit history
     did not. `InlineDiff` sets its own: it renders diff segments directly and
     never reaches this component. */
  .markdown {
    white-space: pre-wrap;
  }
</style>
