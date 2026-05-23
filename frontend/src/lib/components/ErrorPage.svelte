<script lang="ts">
  import type { Snippet } from 'svelte';
  import { SITE_TITLE } from '$lib/constants';
  import Page from './Page.svelte';

  let {
    heading,
    body,
    cta,
  }: {
    heading: string;
    body: string;
    cta: Snippet;
  } = $props();
</script>

<svelte:head>
  <title>{heading} — {SITE_TITLE}</title>
</svelte:head>

<Page width="narrow">
  <div class="error-content">
    <section class="error-card" role="alert">
      <h1>{heading}</h1>
      <p class="body">{body}</p>
      <div class="cta-row">{@render cta()}</div>
    </section>
  </div>
</Page>

<style>
  .error-content {
    padding: var(--size-6) var(--size-4);
  }

  .error-card {
    display: flex;
    flex-direction: column;
    gap: var(--size-4);
    padding: var(--size-5);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    background: var(--color-surface);
  }

  h1 {
    margin: 0;
    font-size: var(--font-size-3);
  }

  .body {
    margin: 0;
    color: var(--color-text-muted);
  }

  .cta-row {
    display: flex;
  }
</style>
