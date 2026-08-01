<!-- @component Theme detail page: description, hierarchy and the games listing pinned to the theme. -->
<script lang="ts">
  import AttributionLine from '$lib/components/provenance/AttributionLine.svelte';
  import GamesSection from '$lib/components/pages/record/detail/GamesSection.svelte';
  import HierarchicalTaxonomyChildrenAccordion from '$lib/components/pages/record/detail/HierarchicalTaxonomyChildrenAccordion.svelte';
  import HierarchicalTaxonomyMobileMetaBar from '$lib/components/pages/record/detail/HierarchicalTaxonomyMobileMetaBar.svelte';
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

<GamesSection games={theme.games} q={data.q} />

<style>
  .description {
    margin-bottom: var(--size-6);
  }
</style>
