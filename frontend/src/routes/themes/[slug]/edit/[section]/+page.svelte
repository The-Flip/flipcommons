<script lang="ts">
  import TaxonomyEditSectionPageBase from '$lib/components/pages/record/edit/TaxonomyEditSectionPageBase.svelte';
  import HierarchicalTaxonomyEditorSwitch from '$lib/components/pages/record/edit/editors/entity/taxonomy/HierarchicalTaxonomyEditorSwitch.svelte';
  import {
    defaultHierarchicalTaxonomySectionSegment,
    HIERARCHICAL_TAXONOMY_EDIT_SECTIONS,
    type HierarchicalTaxonomyEditSectionKey,
  } from '$lib/components/pages/record/edit/editors/entity/taxonomy/hierarchical-taxonomy-edit-sections';

  let { data } = $props();
  let theme = $derived(data.profile);

  const sections = HIERARCHICAL_TAXONOMY_EDIT_SECTIONS.map((section) =>
    section.key === 'parents' ? { ...section, label: 'Parent Themes' } : section,
  );
</script>

<TaxonomyEditSectionPageBase
  basePath="/themes"
  {sections}
  defaultSegment={defaultHierarchicalTaxonomySectionSegment()}
>
  {#snippet editor(
    key: HierarchicalTaxonomyEditSectionKey,
    { ref, onsaved, onerror, ondirtychange },
  )}
    <HierarchicalTaxonomyEditorSwitch
      sectionKey={key}
      initialData={theme}
      slug={theme.slug}
      claimsPath={'/api/themes/{public_id}/claims/'}
      parentType="theme"
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}
</TaxonomyEditSectionPageBase>
