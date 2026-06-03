<script lang="ts">
  import client from '$lib/api/client';
  import TaxonomyEditSectionPageBase from '$lib/components/pages/record/edit/TaxonomyEditSectionPageBase.svelte';
  import HierarchicalTaxonomyEditorSwitch from '$lib/components/editors/HierarchicalTaxonomyEditorSwitch.svelte';
  import MediaEditor from '$lib/components/editors/MediaEditor.svelte';
  import {
    defaultHierarchicalTaxonomySectionSegment,
    HIERARCHICAL_TAXONOMY_EDIT_SECTIONS,
    MEDIA_SECTION,
    type HierarchicalTaxonomyEditSectionKey,
  } from '$lib/components/editors/hierarchical-taxonomy-edit-sections';

  let { data } = $props();
  let profile = $derived(data.profile);

  const sections = [
    ...HIERARCHICAL_TAXONOMY_EDIT_SECTIONS.map((section) =>
      section.key === 'parents' ? { ...section, label: 'Parent Features' } : section,
    ),
    MEDIA_SECTION,
  ];

  async function loadParentOptions() {
    const { data: features } = await client.GET('/api/gameplay-features/all/');
    if (!features) return [];
    return features.map((f) => ({
      slug: f.slug,
      label: f.name,
      count: f.title_count,
    }));
  }
</script>

<TaxonomyEditSectionPageBase
  basePath="/gameplay-features"
  {sections}
  defaultSegment={defaultHierarchicalTaxonomySectionSegment()}
>
  {#snippet editor(
    key: HierarchicalTaxonomyEditSectionKey,
    { ref, onsaved, onerror, ondirtychange },
  )}
    <HierarchicalTaxonomyEditorSwitch
      sectionKey={key}
      initialData={profile}
      slug={profile.slug}
      claimsPath={'/api/gameplay-features/{public_id}/claims/'}
      parentOptionsLoader={loadParentOptions}
      parentsLabel="This feature is a type of..."
      bind:editorRef={ref.current}
      {onsaved}
      {onerror}
      {ondirtychange}
    />
  {/snippet}

  {#snippet immediateEditor()}
    <MediaEditor
      entityType="gameplay-feature"
      slug={profile.slug}
      media={profile.uploaded_media ?? []}
    />
  {/snippet}
</TaxonomyEditSectionPageBase>
