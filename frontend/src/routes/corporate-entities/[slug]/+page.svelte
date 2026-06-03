<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import SearchableGrid from '$lib/components/collections/grid/SearchableGrid.svelte';
  import TitleCard from '$lib/components/collections/cards/TitleCard.svelte';

  let { data } = $props();
  let ce = $derived(data.profile);
  let titlesHeading = $derived(`Titles by ${ce.name}`);
</script>

{#if ce.description?.html}
  <div class="description">
    <Markdown html={ce.description.html} citations={ce.description.citations} />
    <AttributionLine attribution={ce.description.attribution} />
  </div>
{/if}

{#if ce.titles.length === 0}
  <p class="empty">No titles listed for this corporate entity.</p>
{:else}
  <section class="titles">
    <h2>{titlesHeading}</h2>
    <SearchableGrid
      items={ce.titles}
      filterFields={(item) => [item.name]}
      placeholder="Search titles..."
      entityName="title"
    >
      {#snippet children(title)}
        <TitleCard
          slug={title.public_id}
          name={title.name}
          thumbnailUrl={title.thumbnail_url}
          year={title.year}
        />
      {/snippet}
    </SearchableGrid>
  </section>
{/if}

<style>
  .description {
    margin-bottom: var(--size-5);
  }

  .titles h2 {
    font-size: var(--font-size-4);
    font-weight: 600;
    margin: 0 0 var(--size-3);
  }

  .empty {
    color: var(--color-text-muted);
    font-size: var(--font-size-2);
    padding: var(--size-8) 0;
    text-align: center;
  }
</style>
