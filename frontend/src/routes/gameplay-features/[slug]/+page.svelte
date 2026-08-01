<!-- @component Gameplay-feature detail page: description, hierarchy, media and the games listing pinned to the feature (sub-features included). -->
<script lang="ts">
  import { ENTITY_META } from '$lib/entities/entity-meta';
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import HierarchicalTaxonomyChildrenAccordion from '$lib/components/pages/record/detail/HierarchicalTaxonomyChildrenAccordion.svelte';
  import HierarchicalTaxonomyMobileMetaBar from '$lib/components/pages/record/detail/HierarchicalTaxonomyMobileMetaBar.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import Markdown from '$lib/components/markdown/Markdown.svelte';
  import MediaGrid from '$lib/components/media/MediaGrid.svelte';
  import { hierarchicalTaxonomyEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import { displayAliasesFor } from '$lib/hierarchy-edit';

  let { data } = $props();
  let profile = $derived(data.profile);

  const editAction = hierarchicalTaxonomyEditActionContext.get();

  let displayAliases = $derived(displayAliasesFor(profile.name, profile.aliases ?? []));
  let mediaHeading = $derived(`Media (${profile.uploaded_media?.length ?? 0})`);
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

<GamesSection games={profile.games} q={data.q} pinned={{ gameplay_feature: [profile.slug] }} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
