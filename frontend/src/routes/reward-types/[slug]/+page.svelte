<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import ClientFilteredGrid from '$lib/components/collections/grid/ClientFilteredGrid.svelte';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);
</script>

{#if profile.description?.html}
  <section class="description">
    <Markdown html={profile.description.html} citations={profile.description.citations ?? []} />
    <AttributionLine attribution={profile.description.attribution} />
  </section>
{/if}

{#if profile.machines.length === 0}
  <p class="empty">No machines with this reward type.</p>
{:else}
  <section>
    <h2>Machines ({profile.machines.length})</h2>
    <ClientFilteredGrid items={profile.machines} showCount={false}>
      {#snippet children(machine)}
        <GameCard
          entityType="model"
          slug={machine.public_id}
          name={machine.name}
          thumbnailUrl={machine.thumbnail_url}
          manufacturerName={machine.manufacturer?.name}
          year={machine.year}
        />
      {/snippet}
    </ClientFilteredGrid>
  </section>
{/if}

<style>
  .description {
    margin-bottom: var(--size-6);
  }

  h2 {
    font-size: var(--font-size-3);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: var(--size-3);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
    text-align: center;
  }
</style>
