<!-- @component Plain text whose [n] / [?] cite markers (from
substituteCiteMarkers) render as superscripts. Pass `interactions` to make them
tooltip-and-jump targets; omit it where there is no reference list to jump to,
and they stay inert labels rather than advertising an interaction. -->
<script lang="ts">
  import { splitCiteMarkers, type CiteMarkerInteractions } from './cite-markers';

  let {
    text,
    interactions,
  }: {
    text: string;
    interactions?: CiteMarkerInteractions;
  } = $props();

  /** The reference number and citation id behind a marker, or null when it
   *  is inert — a `[?]`, or a number this surface gave no identity for. */
  function liveMarker(
    marker: string,
    ids: Map<number, number> | undefined,
  ): { index: number; id: number } | null {
    if (!ids) return null;
    const digits = marker.slice(1, -1);
    if (!/^\d+$/.test(digits)) return null;
    const index = Number(digits);
    const id = ids.get(index);
    return id == null ? null : { index, id };
  }
</script>

{#each splitCiteMarkers(text) as part, i (i)}
  {#if part.type === 'marker'}{@const live = liveMarker(
      part.text,
      interactions?.ids,
    )}{#if live && interactions}<sup class="cite-marker"
        ><a
          href={interactions.hrefFor(live.index)}
          class:flash={live.index === interactions.flashIndex}
          data-cite-id={live.id}
          data-cite-index={live.index}
          aria-label="Citation {live.index}">{part.text}</a
        ></sup
      >{:else}<sup class="cite-marker">{part.text}</sup>{/if}{:else}{part.text}{/if}
{/each}

<style>
  sup.cite-marker {
    font-size: var(--font-size-00, 0.75rem);
    color: var(--color-link);
    line-height: 0;
  }

  sup.cite-marker a {
    color: inherit;
    text-decoration: none;
  }

  sup.cite-marker a:hover,
  sup.cite-marker a:focus-visible {
    text-decoration: underline;
  }

  sup.cite-marker a.flash {
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
