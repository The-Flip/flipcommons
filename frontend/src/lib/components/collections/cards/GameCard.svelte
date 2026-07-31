<!-- @component The one listing card for a game — a Title or a Model. Identical rendering for both; only the href differs, resolved through the entity registry rather than a branch. -->
<script lang="ts">
  import { ENTITY_META } from '$lib/entities/entity-meta';
  import { UNKNOWN_MANUFACTURER_LABEL } from '$lib/entities/manufacturer';
  import { resolveHref } from '$lib/utils';
  import Card from './Card.svelte';

  let {
    entityType,
    publicId,
    name,
    thumbnailUrl = null,
    manufacturerName = null,
    year = null,
    roles = null,
    showManufacturer = true,
  }: {
    /** Which record the card fronts. Decides only the href, via ENTITY_META. */
    entityType: 'title' | 'model';
    publicId: string;
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

<Card
  href={resolveHref(`/${ENTITY_META[entityType].entity_type_plural}/${publicId}`)}
  title={name}
  {thumbnailUrl}
>
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
