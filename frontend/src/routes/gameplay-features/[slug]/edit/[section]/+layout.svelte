<script lang="ts">
  import type { Snippet } from 'svelte';
  import TaxonomyEditSectionLayoutBase from '$lib/components/pages/record/edit/TaxonomyEditSectionLayoutBase.svelte';
  import {
    defaultHierarchicalTaxonomySectionSegment,
    HIERARCHICAL_TAXONOMY_EDIT_SECTIONS,
    MEDIA_SECTION,
  } from '$lib/components/editors/hierarchical-taxonomy-edit-sections';

  let { children }: { children: Snippet } = $props();

  const sections = [
    ...HIERARCHICAL_TAXONOMY_EDIT_SECTIONS.map((section) =>
      section.key === 'parents' ? { ...section, label: 'Parent Features' } : section,
    ),
    MEDIA_SECTION,
  ];
</script>

<TaxonomyEditSectionLayoutBase
  basePath="/gameplay-features"
  {sections}
  defaultSegment={defaultHierarchicalTaxonomySectionSegment()}
>
  {@render children()}
</TaxonomyEditSectionLayoutBase>
