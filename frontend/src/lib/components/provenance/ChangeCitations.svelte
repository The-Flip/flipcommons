<!-- @component Citations footer for one field change: numbered rows for inline
[[cite:]] citations (matching the [n] markers in the change's text), unnumbered
rows for evidence attached directly to the claim. Each row shows its verbatim
supporting quote beneath the source line when one was recorded. -->
<script lang="ts">
  import type { FieldChangeCitationSchema } from '$lib/api/schema';
  import { displayLocator } from '$lib/citation-types';
  import { citationLinkDisplay } from '$lib/components/citation/citation-links';

  let {
    citations,
    indexes,
  }: {
    citations: FieldChangeCitationSchema[];
    /** Per-change footnote numbers keyed by citation-instance slug (see
     *  `assignCiteIndexes`); attached citations have no slug and no number. */
    indexes: Map<string, number>;
  } = $props();

  interface Entry {
    citation: FieldChangeCitationSchema;
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
      {@const links = citationLinkDisplay(citation.links ?? [])}
      <div class="citation-row">
        {#if index !== undefined}
          <span class="marker">{index}.</span>
        {/if}
        <div class="citation-body">
          <span class="source-line" class:with-quote={Boolean(citation.quote)}>
            <strong>
              {#if links.titleHref}
                <a href={links.titleHref} target="_blank">{citation.source_name}</a>
              {:else}
                {citation.source_name}
              {/if}
            </strong>
            {#if citation.author || citation.year}
              <span class="meta">
                &mdash; {[citation.author, citation.year].filter(Boolean).join(', ')}
              </span>
            {/if}
            {#if citation.locator}
              <span class="meta">({displayLocator(citation.source_type, citation.locator)})</span>
            {/if}
            {#each links.chips as link (link.url)}
              <a class="chip" href={link.url} target="_blank">{link.display_name}</a>
            {/each}
          </span>
          {#if citation.quote}
            <blockquote class="quote">{citation.quote}</blockquote>
          {/if}
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

  /* Colon tying the source identity to its quote below; ::after hugs whatever
     the last inline piece is (name, locator or a link chip) with no stray gap. */
  .source-line.with-quote::after {
    content: ':';
  }

  .quote {
    /* Open Props normalize gives blockquote display:grid and a readable-measure
       max-inline-size; neither fits this full-width evidence row. */
    display: block;
    max-inline-size: none;
    margin: 0;
    padding-left: var(--size-3);
    border-left: 2px solid var(--color-border-soft);
    font-style: italic;
    color: var(--color-text-muted);
  }

  strong {
    color: var(--color-text);
  }

  strong a {
    color: inherit;
    text-decoration: none;
  }

  strong a:hover {
    text-decoration: underline;
  }

  .meta {
    color: var(--color-text-muted);
  }

  .chip {
    margin-left: var(--size-1);
    color: var(--color-link);
    text-decoration: none;
  }

  .chip:hover {
    text-decoration: underline;
  }
</style>
