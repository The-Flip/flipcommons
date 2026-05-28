<script lang="ts">
  import client from '$lib/api/client';
  import TaxonomyEditSectionPageBase from '$lib/components/TaxonomyEditSectionPageBase.svelte';
  import HierarchicalTaxonomyEditorSwitch from '$lib/components/editors/HierarchicalTaxonomyEditorSwitch.svelte';
  import {
    defaultHierarchicalTaxonomySectionSegment,
    HIERARCHICAL_TAXONOMY_EDIT_SECTIONS,
    type HierarchicalTaxonomyEditSectionKey,
  } from '$lib/components/editors/hierarchical-taxonomy-edit-sections';

  let { data } = $props();
  let theme = $derived(data.profile);

  const sections = HIERARCHICAL_TAXONOMY_EDIT_SECTIONS.map((section) =>
    section.key === 'parents' ? { ...section, label: 'Parent Themes' } : section,
  );

  async function loadParentOptions() {
    const { data: themes } = await client.GET('/api/themes/');
    if (!themes) return [];
    return themes.map((t) => ({
      slug: t.slug,
      label: t.name,
    }));
  }
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
      parentOptionsLoader={loadParentOptions}
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}
</TaxonomyEditSectionPageBase>
