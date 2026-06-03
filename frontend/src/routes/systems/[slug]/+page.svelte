<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import ClientFilteredGrid from '$lib/components/collections/grid/ClientFilteredGrid.svelte';
  import TitleCard from '$lib/components/collections/cards/TitleCard.svelte';

  let { data } = $props();
  let system = $derived(data.profile);
</script>

{#if system.description?.html}
  <section class="description">
    <Markdown html={system.description.html} citations={system.description.citations ?? []} />
    <AttributionLine attribution={system.description.attribution} />
  </section>
{/if}

<section>
  <h2>Titles using {system.name} ({system.titles.length})</h2>
  {#if system.titles.length === 0}
    <p class="empty">No titles on this system.</p>
  {:else}
    <ClientFilteredGrid items={system.titles} showCount={false}>
      {#snippet children(title)}
        <TitleCard
          slug={title.public_id}
          name={title.name}
          thumbnailUrl={title.thumbnail_url}
          manufacturerName={title.manufacturer_name}
          year={title.year}
        />
      {/snippet}
    </ClientFilteredGrid>
  {/if}
</section>

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
