<script lang="ts">
  import CitationTooltip from './CitationTooltip.svelte';
  import type { InlineCitation } from './citation-tooltip';

  let {
    html,
    htmlSignal = html,
    citations = undefined,
  }: {
    html: string;
    htmlSignal?: string;
    citations?: InlineCitation[];
  } = $props();

  let container: HTMLDivElement | undefined = $state();
</script>

<!-- eslint-disable-next-line svelte/no-at-html-tags -->
<div bind:this={container}>{@html html}</div>
<CitationTooltip {container} {htmlSignal} {citations} />
