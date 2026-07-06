<!-- @component A citation's identity block: the source name (hyperlinked to
  its reference URL when it has one), byline, locator and supporting-link
  chips. Shared by the citation tooltip and the sources panel. -->
<script lang="ts">
  import { displayLocator } from '$lib/citation-types';
  import { citationLinkDisplay, type CitationLink } from './citation-links';

  let {
    sourceName,
    sourceType,
    author,
    year = null,
    locator,
    links,
    quote = '',
    clampQuote = false,
    linkLayout = 'column',
  }: {
    sourceName: string;
    sourceType: string;
    author: string;
    year?: number | null;
    locator: string;
    links: CitationLink[];
    /** Optional supporting quote, shown between the locator and the links. */
    quote?: string;
    /** Clamp a long quote to a few lines (for tight surfaces like the
     *  tooltip). Off by default so the sources panel shows it in full. */
    clampQuote?: boolean;
    /** How to lay out the supporting-link chips. */
    linkLayout?: 'column' | 'row';
  } = $props();

  let byline = $derived([author, year].filter(Boolean).join(', '));
  let display = $derived(citationLinkDisplay(links));
</script>

<div class="source-name">
  {#if display.titleHref}
    <a href={display.titleHref} target="_blank">{sourceName}</a>
  {:else}
    {sourceName}
  {/if}
</div>
{#if byline}
  <div class="meta">{byline}</div>
{/if}
{#if locator}
  <div class="locator">{displayLocator(sourceType, locator)}</div>
{/if}
{#if quote}
  <blockquote class="quote" class:clamped={clampQuote}>{quote}</blockquote>
{/if}
{#if display.chips.length > 0}
  <div class="links" class:row={linkLayout === 'row'}>
    {#each display.chips as link (link.url)}
      <a href={link.url} target="_blank">{link.display_name}</a>
    {/each}
  </div>
{/if}

<style>
  .source-name {
    font-weight: 600;
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

  .links.row {
    flex-direction: row;
    flex-wrap: wrap;
    gap: var(--size-2);
    margin-top: 0;
  }

  .links a {
    color: var(--color-link);
    text-decoration: none;
    font-size: var(--font-size-0);
  }

  .links a:hover {
    text-decoration: underline;
  }
</style>
