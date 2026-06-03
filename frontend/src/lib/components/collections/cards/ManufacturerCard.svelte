<script lang="ts">
  import { resolve } from '$app/paths';
  import Card from './Card.svelte';

  let {
    slug,
    name,
    thumbnailUrl = null,
    modelCount = 0,
  }: {
    slug: string;
    name: string;
    thumbnailUrl?: string | null;
    modelCount?: number;
  } = $props();
</script>

<Card href={resolve(`/manufacturers/${slug}`)} title={name} {thumbnailUrl}>
  <p class="card-count">{modelCount} model{modelCount === 1 ? '' : 's'}</p>
</Card>

<style>
  .card-count {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
  }
</style>
