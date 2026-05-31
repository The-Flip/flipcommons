<script lang="ts">
  import type { ClaimAttributionSchema } from '$lib/api/schema';
  import UserLink from '$lib/components/UserLink.svelte';

  let { attribution }: { attribution: ClaimAttributionSchema } = $props();
  const author = $derived(attribution.author);
</script>

{#if author.kind === 'source'}
  <span class="source-badge">{author.name}</span>
{:else}
  <UserLink username={author.username} />
{/if}

<style>
  .source-badge {
    display: inline-block;
    padding: 1px var(--size-2);
    font-size: var(--font-size-00, 0.7rem);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-radius: var(--radius-1);
    background-color: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    color: var(--color-text-muted);
  }
</style>
