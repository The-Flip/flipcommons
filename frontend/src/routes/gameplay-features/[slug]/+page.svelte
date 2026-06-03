<script lang="ts">
  import client from '$lib/api/client';
  import { ENTITY_META } from '$lib/entities/entity-meta';
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import HierarchicalTaxonomyChildrenAccordion from '$lib/components/pages/record/detail/HierarchicalTaxonomyChildrenAccordion.svelte';
  import HierarchicalTaxonomyMobileMetaBar from '$lib/components/pages/record/detail/HierarchicalTaxonomyMobileMetaBar.svelte';
  import MachineCard from '$lib/components/collections/cards/MachineCard.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';
  import PaginatedSection from '$lib/components/collections/grid/PaginatedSection.svelte';
  import { hierarchicalTaxonomyEditActionContext } from '$lib/components/editors/edit-action-context';
  import { displayAliasesFor } from '$lib/hierarchy-edit';
  import { createPaginatedLoader, unwrapPage } from '$lib/paginated-loader.svelte';

  let { data } = $props();
  let profile = $derived(data.profile);

  const editAction = hierarchicalTaxonomyEditActionContext.get();

  let displayAliases = $derived(displayAliasesFor(profile.name, profile.aliases ?? []));
  let mediaHeading = $derived(`Media (${profile.uploaded_media?.length ?? 0})`);

  const machines = createPaginatedLoader(async (page) => {
    const { data: result } = await client.GET('/api/models/', {
      params: { query: { feature: profile.slug, page } },
    });
    return unwrapPage(result);
  });
</script>

{#if profile.description?.html}
  <section class="description">
    <Markdown html={profile.description.html} citations={profile.description.citations ?? []} />
    <AttributionLine attribution={profile.description.attribution} />
  </section>
{/if}

<HierarchicalTaxonomyMobileMetaBar
  basePath="/gameplay-features"
  parents={profile.parents ?? []}
  aliases={displayAliases}
  parentLabel="Type of"
/>

<HierarchicalTaxonomyChildrenAccordion
  basePath="/gameplay-features"
  children={profile.children ?? []}
  heading="Subtypes"
/>

{#if (profile.uploaded_media?.length ?? 0) > 0}
  <AccordionSection heading={mediaHeading} onEdit={editAction('media')}>
    <MediaGrid
      media={profile.uploaded_media ?? []}
      categories={[...ENTITY_META['gameplay-feature'].media_categories]}
      canEdit={false}
    />
  </AccordionSection>
{/if}

<PaginatedSection
  loader={machines}
  heading="Machines"
  emptyMessage="No machines with this feature."
>
  {#snippet children(machine)}
    <MachineCard
      slug={machine.slug}
      name={machine.name}
      thumbnailUrl={machine.thumbnail_url}
      manufacturerName={machine.manufacturer?.name}
      year={machine.year}
    />
  {/snippet}
</PaginatedSection>

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
