<!-- @component Citations footer for one field change: numbered rows for inline
[[cite:]] citations (matching the [n] markers in the change's text), unnumbered
rows for evidence attached directly to the claim. Owns the marker numbering and
ordering; each row's identity is rendered by CitationBody in its inline layout. -->
<script lang="ts">
  import type { ClaimCitationSchema } from '$lib/api/schema';
  import CitationBody from '$lib/components/citation/CitationBody.svelte';

  let {
    citations,
    indexes,
  }: {
    citations: ClaimCitationSchema[];
    /** Per-change footnote numbers keyed by citation-instance slug (see
     *  `assignCiteIndexes`); attached citations have no slug and no number. */
    indexes: Map<string, number>;
  } = $props();

  interface Entry {
    citation: ClaimCitationSchema;
    index: number | undefined;
  }

  /** Numbered (inline) entries in marker order, then unnumbered (attached) ones. */
  let entries = $derived.by(() => {
    const numbered: Entry[] = [];
    const unnumbered: Entry[] = [];
    for (const citation of citations) {
      const index = citation.slug != null ? indexes.get(citation.slug) : undefined;
      (index === undefined ? unnumbered : numbered).push({ citation, index });
    }
    numbered.sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
    return [...numbered, ...unnumbered];
  });
</script>

{#if entries.length > 0}
  <dd class="change-citations">
    {#each entries as { citation, index }, i (citation.slug ?? `attached-${i}`)}
      <div class="citation-row">
        {#if index !== undefined}
          <span class="marker">{index}.</span>
        {/if}
        <div class="citation-body">
          <CitationBody {citation} layout="inline" />
        </div>
      </div>
    {/each}
  </dd>
{/if}

<style>
  .change-citations {
    flex-basis: 100%;
    font-size: var(--font-size-0);
    line-height: var(--font-lineheight-3);
    color: var(--color-text-muted);
  }

  .citation-row {
    display: flex;
    gap: var(--size-1);
    align-items: baseline;
  }

  .marker {
    min-width: 1.2em;
    text-align: right;
  }

  .citation-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--size-1);
  }
</style>
