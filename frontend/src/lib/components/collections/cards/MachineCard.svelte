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

  let hasMeta = $derived(!!manufacturerName || !!year);
</script>

<Card href={resolve(`/models/${slug}`)} title={name} {thumbnailUrl}>
  {#if hasMeta}
    <div class="card-meta">
      {#if manufacturerName}
        <span>{manufacturerName}</span>
      {/if}
      {#if year}
        <span>{year}</span>
      {/if}
    </div>
  {/if}
  {#if roles && roles.length > 0}
    <div class="card-roles">{roles.join(', ')}</div>
  {/if}
</Card>

<style>
  .card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-1);
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }

  .card-meta span:not(:last-child)::after {
    content: '·';
    margin-left: var(--size-1);
  }

  .card-roles {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    font-style: italic;
  }
</style>
