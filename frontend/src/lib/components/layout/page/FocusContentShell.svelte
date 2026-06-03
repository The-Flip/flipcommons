<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    backHref,
    recordName,
    recordHref,
    maxWidth = '48rem',
    heading,
    children,
  }: {
    backHref: string;
    recordName?: string;
    recordHref?: string;
    maxWidth?: string;
    heading: Snippet;
    children: Snippet;
  } = $props();
</script>

<div class="focus-shell" style:max-width={maxWidth}>
  <header class="focus-header">
    <a href={backHref} class="back-link">
      <span class="back-arrow" aria-hidden="true">&larr;</span>
      <span class="back-text">Back</span>
    </a>
    {#if recordName && recordHref}
      <a href={recordHref} class="record-name" title={recordName}>{recordName}</a>
    {/if}
    <div class="heading-slot">
      {@render heading()}
    </div>
  </header>

  {@render children()}
</div>

<style>
  .focus-shell {
    margin: 0 auto;
    padding: var(--size-4);
  }

  .focus-header {
    display: flex;
    align-items: center;
    gap: var(--size-3);
    padding-bottom: var(--size-3);
    margin-bottom: var(--size-4);
    min-height: 2.5rem;
    border-bottom: 1px solid var(--color-border-soft);
  }

  .back-link {
    display: inline-flex;
    align-items: baseline;
    gap: 0.25em;
    flex-shrink: 0;
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    text-decoration: none;
  }

  .back-link:hover {
    color: var(--color-text);
  }

  .record-name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    text-decoration: none;
  }

  .record-name:hover {
    text-decoration: underline;
  }

  .heading-slot {
    flex-shrink: 0;
    margin-left: auto;
  }

  @media not (--breakpoint-wide) {
    .back-text {
      display: none;
    }
  }
</style>
