<!-- @component Plain text whose [n] / [?] cite markers (from
substituteCiteMarkers) render as superscripts. -->
<script lang="ts">
  import { splitCiteMarkers } from './cite-markers';

  let { text }: { text: string } = $props();
</script>

{#each splitCiteMarkers(text) as part, i (i)}
  {#if part.type === 'marker'}<sup class="cite-marker">{part.text}</sup>{:else}{part.text}{/if}
{/each}

<style>
  sup.cite-marker {
    font-size: var(--font-size-00, 0.75rem);
    color: var(--color-link);
    line-height: 0;
  }
</style>
