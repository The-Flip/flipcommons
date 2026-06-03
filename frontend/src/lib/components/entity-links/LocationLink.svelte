<script lang="ts">
  import type { CorporateEntityLocationSchema } from '$lib/api/schema';
  import { buildLocationParts } from '$lib/location-links';
  import { resolveHref } from '$lib/utils';

  let {
    loc,
  }: {
    loc: CorporateEntityLocationSchema;
  } = $props();

  type Part = { text: string; href?: string };

  let parts = $derived.by((): Part[] =>
    buildLocationParts(loc).map((part) => ({
      ...part,
      href: part.href ? resolveHref(part.href) : undefined,
    })),
  );
</script>

{#if parts.length > 0}
  <span class="location">
    {#each parts as part, j (j)}
      {#if j > 0},
      {/if}
      {#if part.href}<a href={part.href}>{part.text}</a>{:else}{part.text}{/if}
    {/each}
  </span>
{/if}

<style>
  .location {
    font-style: italic;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .location a {
    color: var(--color-link);
    text-decoration: none;
  }

  .location a:hover {
    text-decoration: underline;
  }
</style>
