<script lang="ts">
  import { resolve } from '$app/paths';
  import Card from './Card.svelte';

  let {
    slug,
    name,
    thumbnailUrl = null,
    creditCount = 0,
    creditLabel = 'credit',
  }: {
    slug: string;
    name: string;
    thumbnailUrl?: string | null;
    creditCount?: number;
    creditLabel?: string;
  } = $props();
</script>

<Card href={resolve(`/people/${slug}`)} title={name} {thumbnailUrl}>
  <p class="card-count">{creditCount} {creditLabel}{creditCount === 1 ? '' : 's'}</p>
</Card>

<style>
  .card-count {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }
</style>
