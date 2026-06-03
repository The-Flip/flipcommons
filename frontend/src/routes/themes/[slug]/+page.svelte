<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import ClientFilteredGrid from '$lib/components/collections/grid/ClientFilteredGrid.svelte';
  import HierarchicalTaxonomyChildrenAccordion from '$lib/components/pages/record/detail/HierarchicalTaxonomyChildrenAccordion.svelte';
  import HierarchicalTaxonomyMobileMetaBar from '$lib/components/pages/record/detail/HierarchicalTaxonomyMobileMetaBar.svelte';
  import MachineCard from '$lib/components/collections/cards/MachineCard.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';

  let { data } = $props();
  let theme = $derived(data.profile);

  let childHeading = 'Sub-themes';
</script>

{#if theme.description?.html}
  <section class="description">
    <Markdown html={theme.description.html} citations={theme.description.citations ?? []} />
    <AttributionLine attribution={theme.description.attribution} />
  </section>
{/if}

<HierarchicalTaxonomyMobileMetaBar
  basePath="/themes"
  parents={theme.parents ?? []}
  aliases={[]}
  parentLabel="Parent themes"
/>

<HierarchicalTaxonomyChildrenAccordion
  basePath="/themes"
  children={theme.children ?? []}
  heading={childHeading}
  headingSize="var(--font-size-3)"
/>

<h2 class="section-heading">Titles</h2>

{#if theme.machines.length === 0}
  <p class="empty">No machines with this theme.</p>
{:else}
  <ClientFilteredGrid items={theme.machines} showCount={false}>
    {#snippet children(machine)}
      <MachineCard
        slug={machine.public_id}
        name={machine.name}
        thumbnailUrl={machine.thumbnail_url}
        manufacturerName={machine.manufacturer?.name}
        year={machine.year}
      />
    {/snippet}
  </ClientFilteredGrid>
{/if}

<style>
  .description {
    margin-bottom: var(--size-6);
  }

  .section-heading {
    font-size: var(--font-size-3);
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
