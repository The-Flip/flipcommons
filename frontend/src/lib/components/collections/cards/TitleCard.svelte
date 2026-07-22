<script lang="ts">
  import { resolve } from '$app/paths';
  import { UNKNOWN_MANUFACTURER_LABEL } from '$lib/entities/manufacturer';
  import Card from './Card.svelte';

  let {
    slug,
    name,
    thumbnailUrl = null,
    manufacturerName = null,
    year = null,
    roles = null,
    showManufacturer = true,
  }: {
    slug: string;
    name: string;
    thumbnailUrl?: string | null;
    manufacturerName?: string | null;
    year?: number | null;
    roles?: string[] | null;
    /**
     * Whether the tile carries a manufacturer line at all. Set false where the
     * maker is already the page subject (a manufacturer or corporate-entity
     * page) — there a missing `manufacturerName` means "redundant", not
     * "unknown", and the fallback label would be a lie.
     */
    showManufacturer?: boolean;
  } = $props();

  const subtitle = $derived(
    [showManufacturer ? manufacturerName || UNKNOWN_MANUFACTURER_LABEL : null, year]
      .filter(Boolean)
      .join(', '),
  );
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
