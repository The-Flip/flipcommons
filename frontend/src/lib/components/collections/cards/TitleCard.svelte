<script lang="ts">
  import { resolve } from '$app/paths';
  import Card from './Card.svelte';

  let {
    slug,
    name,
    thumbnailUrl = null,
    manufacturerName = null,
    year = null,
    roles = null,
  }: {
    slug: string;
    name: string;
    thumbnailUrl?: string | null;
    manufacturerName?: string | null;
    year?: number | null;
    roles?: string[] | null;
  } = $props();

  const subtitle = $derived([manufacturerName, year].filter(Boolean).join(', ') || null);
</script>

<Card href={resolve(`/titles/${slug}`)} title={name} {thumbnailUrl}>
  {#if subtitle}
    <p class="card-subtitle">{subtitle}</p>
  {/if}
  {#if roles && roles.length > 0}
    <p class="card-roles">{roles.join(', ')}</p>
  {/if}
</Card>

<style>
  .card-subtitle {
    font-size: var(--font-size-1);
    color: var(--color-text-muted);
    margin: 0;
  }

  .card-roles {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    font-style: italic;
    margin: 0;
  }
</style>
