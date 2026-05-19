<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    density = 'loose',
    children,
  }: {
    density?: 'loose' | 'tight';
    children: Snippet;
  } = $props();
</script>

<div class="prose prose-{density}">{@render children()}</div>

<style>
  .prose {
    font-size: var(--font-size-2);
    line-height: var(--font-lineheight-3);
    color: var(--color-text);
  }

  .prose :global(h1),
  .prose :global(h2),
  .prose :global(h3),
  .prose :global(h4),
  .prose :global(h5),
  .prose :global(h6) {
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-2);
  }

  .prose :global(ul),
  .prose :global(ol) {
    padding-left: var(--size-5);
  }

  .prose :global(a) {
    color: var(--color-link);
    text-decoration: none;
  }

  .prose :global(a:hover) {
    text-decoration: underline;
  }

  .prose :global(strong) {
    font-weight: 700;
  }

  .prose :global(blockquote) {
    border-left: 3px solid var(--color-border);
    padding-left: var(--size-4);
    color: var(--color-text-muted);
    margin-top: 0;
    margin-left: 0;
    margin-right: 0;
  }

  .prose :global(code) {
    font-family: var(--font-mono);
    font-size: 0.9em;
    background: var(--color-surface);
    padding: 0.1em 0.3em;
    border-radius: var(--radius-1);
  }

  .prose :global(pre) {
    background: var(--color-surface);
    padding: var(--size-3);
    border-radius: var(--radius-2);
    overflow-x: auto;
  }

  .prose :global(pre code) {
    background: none;
    padding: 0;
  }

  .prose :global(hr) {
    border: none;
    border-top: 1px solid var(--color-border-soft);
  }

  .prose :global(table) {
    border-collapse: collapse;
    width: 100%;
  }

  .prose :global(th),
  .prose :global(td) {
    border: 1px solid var(--color-border-soft);
    padding: var(--size-1) var(--size-2);
    text-align: left;
  }

  .prose :global(th) {
    font-weight: 600;
  }

  .prose-loose :global(h1) {
    font-size: var(--font-size-7);
    font-weight: 700;
  }
  .prose-loose :global(h2) {
    font-size: var(--font-size-4);
    margin-top: var(--size-7);
    margin-bottom: var(--size-3);
  }
  .prose-loose :global(h3) {
    font-size: var(--font-size-3);
    margin-top: var(--size-5);
  }
  .prose-loose :global(p) {
    margin-bottom: var(--size-4);
  }
  .prose-loose :global(ul),
  .prose-loose :global(ol) {
    margin-bottom: var(--size-4);
  }
  .prose-loose :global(li) {
    margin-bottom: var(--size-2);
  }
  .prose-loose :global(blockquote) {
    margin-bottom: var(--size-4);
  }
  .prose-loose :global(pre) {
    margin-bottom: var(--size-4);
  }
  .prose-loose :global(table) {
    margin-bottom: var(--size-4);
  }
  .prose-loose :global(hr) {
    margin: var(--size-5) 0;
  }

  .prose-tight :global(p) {
    margin-bottom: var(--size-3);
  }
  .prose-tight :global(p:last-child) {
    margin-bottom: 0;
  }
  .prose-tight :global(ul),
  .prose-tight :global(ol) {
    margin-bottom: var(--size-3);
  }
  .prose-tight :global(li) {
    margin-bottom: var(--size-1);
  }
  .prose-tight :global(blockquote) {
    margin-bottom: var(--size-3);
  }
  .prose-tight :global(pre) {
    margin-bottom: var(--size-3);
  }
  .prose-tight :global(table) {
    margin-bottom: var(--size-3);
  }
  .prose-tight :global(hr) {
    margin: var(--size-4) 0;
  }
</style>
