<!-- @component One side of a field change's value: markdown values with
inline citations render their [[cite:]] tokens as numbered superscripts;
everything else falls through to ClaimValue. -->
<script lang="ts">
  import type { ClaimValueSchema } from '$lib/api/schema';
  import ClaimValue from './ClaimValue.svelte';
  import CiteMarkedText from './CiteMarkedText.svelte';
  import { substituteCiteMarkers } from './cite-markers';

  let {
    value,
    citeIndexes,
  }: {
    value: ClaimValueSchema | null | undefined;
    /** Per-change footnote numbers from `citeIndexesForChange`. */
    citeIndexes: Map<string, number>;
  } = $props();
</script>

{#if value?.display?.kind === 'markdown' && citeIndexes.size > 0}
  <CiteMarkedText text={substituteCiteMarkers(value.display.text, citeIndexes)} />
{:else}
  <ClaimValue {value} />
{/if}
