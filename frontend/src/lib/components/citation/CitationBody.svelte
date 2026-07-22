<!-- @component A citation's identity block: the source name (hyperlinked to
  its reference URL when it has one), byline, locator, supporting quote and
  link chips. The single renderer for a citation's identity across surfaces —
  the citation tooltip, the sources panel and edit-history change rows.

  `layout='stacked'` (default) stacks the pieces as separate blocks; `'inline'`
  runs the name, byline, locator and chips together on one line with the quote
  beneath, for the dense change-history rows. -->
<script lang="ts">
  import { displayLocator } from '$lib/citation-types';
  import { citationLinkDisplay, type CitationIdentity } from './citation-links';

  let {
    citation,
    clampQuote = false,
    layout = 'stacked',
  }: {
    /** The citation to render. Any citation wire schema (inline, evidence,
     *  field-change) satisfies this shape. */
    citation: CitationIdentity;
    /** Clamp a long quote to a few lines (for tight surfaces like the
     *  tooltip). Off by default so the sources panel shows it in full.
     *  Ignored in the inline layout. */
    clampQuote?: boolean;
    /** Overall arrangement: `'stacked'` blocks (tooltip, sources panel) or a
     *  single inline `source-line` with the byline, locator and chips run
     *  together (edit-history change rows). */
    layout?: 'stacked' | 'inline';
  } = $props();

  let byline = $derived([citation.author, citation.year].filter(Boolean).join(', '));
  let display = $derived(citationLinkDisplay(citation.links ?? []));
</script>

{#snippet nameLink()}
  {#if display.titleHref}
    <a href={display.titleHref} target="_blank">{citation.source_name}</a>
  {:else}
    {citation.source_name}
  {/if}
{/snippet}

{#if layout === 'inline'}
  <span class="source-line" class:with-quote={Boolean(citation.quote)}>
    <strong>{@render nameLink()}</strong>
    {#if byline}
      <span class="meta">&mdash; {byline}</span>
    {/if}
    {#if citation.locator}
      <span class="meta">({displayLocator(citation.source_type, citation.locator)})</span>
    {/if}
    {#each display.chips as link (link.url)}
      <a class="chip" href={link.url} target="_blank">{link.display_name}</a>
    {/each}
  </span>
  {#if citation.quote}
    <blockquote class="quote inline-quote">{citation.quote}</blockquote>
  {/if}
{:else}
  <div class="source-name">{@render nameLink()}</div>
  {#if byline}
    <div class="meta">{byline}</div>
  {/if}
  {#if citation.locator}
    <div class="locator">{displayLocator(citation.source_type, citation.locator)}</div>
  {/if}
  {#if citation.quote}
    <blockquote class="quote" class:clamped={clampQuote}>{citation.quote}</blockquote>
  {/if}
  {#if display.chips.length > 0}
    <div class="links">
      {#each display.chips as link (link.url)}
        <a href={link.url} target="_blank">{link.display_name}</a>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .source-name {
    font-weight: 600;
    /* Source name can be a bare URL (nameless source) far longer than the
       tight tooltip; break anywhere so it wraps instead of overflowing. */
    overflow-wrap: anywhere;
  }

  .source-name a {
    color: inherit;
    text-decoration: none;
  }

  .source-name a:hover {
    text-decoration: underline;
  }

  .meta,
  .locator {
    color: var(--color-text-muted);
  }

  .quote {
    margin: 0;
    padding-left: var(--size-3);
    border-left: 2px solid var(--color-border-soft);
    font-size: var(--font-size-0);
    font-style: italic;
    color: var(--color-text-muted);
  }

  .quote.clamped {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    overflow: hidden;
  }

  .links {
    margin-top: var(--size-1);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .links a {
    color: var(--color-link);
    text-decoration: none;
    font-size: var(--font-size-0);
  }

  .links a:hover {
    text-decoration: underline;
  }

  /* Inline layout (edit-history change rows) */
  .source-line {
    /* Break a bare-URL source name rather than overflow the row. */
    overflow-wrap: anywhere;
  }

  .source-line strong {
    color: var(--color-text);
  }

  .source-line strong a {
    color: inherit;
    text-decoration: none;
  }

  .source-line strong a:hover {
    text-decoration: underline;
  }

  /* Colon tying the source identity to its quote below; ::after hugs whatever
     the last inline piece is (name, locator or a link chip) with no stray gap. */
  .source-line.with-quote::after {
    content: ':';
  }

  .inline-quote {
    /* Open Props normalize gives blockquote display:grid and a readable-measure
       max-inline-size; neither fits this full-width evidence row. */
    display: block;
    max-inline-size: none;
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
