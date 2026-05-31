<script lang="ts">
  import type { InlineCitation } from './citation-tooltip';
  import { deduplicateCitations } from './citation-refs';

  let {
    citations,
    open = $bindable(false),
    onBackLink,
    showToggle = true,
  }: {
    citations: InlineCitation[];
    open?: boolean;
    onBackLink: (index: number) => void;
    showToggle?: boolean;
  } = $props();

  let uniqueCitations = $derived(deduplicateCitations(citations));
</script>

<section class="references-section" class:embedded={!showToggle}>
  {#if showToggle}
    <button class="toggle" onclick={() => (open = !open)} aria-expanded={open}>
      References ({uniqueCitations.length})
    </button>
  {/if}
  {#if open || !showToggle}
    <ol>
      {#each uniqueCitations as cite (cite.index)}
        <li data-ref-index={cite.index}>
          <button
            class="back-link"
            onclick={() => onBackLink(cite.index)}
            aria-label="Back to citation {cite.index}">&#x21A9;</button
          >
          <strong>{cite.source_name}</strong>
          {#if cite.author || cite.year}
            <span class="meta">
              &mdash; {[cite.author, cite.year].filter(Boolean).join(', ')}
            </span>
          {/if}
          {#if cite.locator}
            <span class="locator">({cite.locator})</span>
          {/if}
          {#if cite.links.length > 0}
            <span class="links">
              {#each cite.links as link (link.url)}
                <a href={link.url} target="_blank" rel="noopener">{link.label || link.url}</a>
              {/each}
            </span>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  .references-section {
    margin-top: var(--size-4);
    border-top: 1px solid var(--color-border-soft);
    padding-top: var(--size-2);
  }

  .references-section.embedded {
    margin-top: 0;
    border-top: none;
    padding-top: 0;
  }

  .toggle {
    background: none;
    border: none;
    cursor: pointer;
    font-size: var(--font-size-1);
    font-weight: 600;
    color: var(--color-text-muted);
    padding: var(--size-1) 0;
  }

  .toggle:hover {
    color: var(--color-text);
  }

  ol {
    margin: var(--size-2) 0 0;
    padding-left: var(--size-5);
    font-size: var(--font-size-1);
    line-height: var(--font-lineheight-3);
  }

  li {
    margin-bottom: var(--size-2);
  }

  .back-link {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--color-link);
    font-size: var(--font-size-0);
    padding: 0;
    margin-right: var(--size-1);
  }

  .back-link:hover {
    text-decoration: underline;
  }

  .meta,
  .locator {
    color: var(--color-text-muted);
  }

  .links {
    display: inline;
    margin-left: var(--size-1);
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
